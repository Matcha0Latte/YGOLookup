"""ygocdb (百鸽) source adapter — the Simplified Chinese card text source.

The bulk endpoint is a zip containing a single `cards.json`:

    GET https://ygocdb.com/api/v0/cards.zip       -> cards.zip (contains cards.json)
    GET https://ygocdb.com/api/v0/cards.zip.md5   -> md5 of **cards.json**, not the zip

Records are keyed by the official `cid`; the 8-digit passcode is `id` and is
what we join on, because `external_id.ygopro_passcode` already exists for the
cards imported from YGOProDeck.

This adapter is an *enrichment* pass, not a card-creating import: it attaches
Chinese text and Chinese names to cards that already exist. Unmatched cards are
counted and reported, never silently created.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .pipeline import register_raw_source, sha256_text

DEFAULT_TIMEOUT = 120
CARDS_URL = "https://ygocdb.com/api/v0/cards.zip"
MD5_URL = "https://ygocdb.com/api/v0/cards.zip.md5"

SOURCE_NAME = "ygocdb_zh"


@dataclass
class FetchResult:
    payload: bytes
    doc: dict[str, Any]
    path: Path
    json_md5: str
    source_version: str


@dataclass
class ApplyResult:
    records: int = 0
    matched: int = 0
    unmatched: int = 0
    without_passcode: int = 0
    text_rows: int = 0
    name_rows: int = 0
    cid_rows: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "records": self.records,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "without_passcode": self.without_passcode,
            "text_rows": self.text_rows,
            "name_rows": self.name_rows,
            "cid_rows": self.cid_rows,
            "errors": self.errors[:20],
            "error_count": len(self.errors),
        }


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - upstream publishes md5


def read_cards_json(payload: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io_bytes(payload)) as archive:
        names = archive.namelist()
        if "cards.json" not in names:
            raise ValueError(f"cards.zip does not contain cards.json: {names}")
        return json.loads(archive.read("cards.json").decode("utf-8"))


def io_bytes(payload: bytes):
    from io import BytesIO

    return BytesIO(payload)


def published_md5(timeout: int = 30) -> str | None:
    try:
        request = Request(MD5_URL, headers={"User-Agent": "YGOLookup/0.1 (+local research tool)"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
            return response.read().decode("utf-8").strip().strip('"')
    except OSError:
        return None


def fetch(url: str = CARDS_URL, raw_dir: Path = Path("data/raw"), *, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    request = Request(url, headers={"User-Agent": "YGOLookup/0.1 (+local research tool)"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        payload = response.read()

    raw = read_cards_json(payload)
    json_md5 = _md5(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    # The published md5 is of the original bytes, not of a re-serialized dict,
    # so compare against the exact member bytes instead.
    with zipfile.ZipFile(io_bytes(payload)) as archive:
        json_md5 = _md5(archive.read("cards.json"))

    expected = published_md5()
    if expected and json_md5 != expected:
        raise ValueError(f"cards.json md5 mismatch: got {json_md5}, published {expected}")

    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = raw_dir / f"ygocdb-{stamp}-{json_md5[:8]}.zip"
    path.write_bytes(payload)

    return FetchResult(
        payload=payload,
        doc=raw,
        path=path,
        json_md5=json_md5,
        source_version=datetime.now().strftime("%Y-%m-%d"),
    )


def load_local(path: str | Path) -> FetchResult:
    payload = Path(path).read_bytes()
    doc = read_cards_json(payload)
    with zipfile.ZipFile(io_bytes(payload)) as archive:
        json_md5 = _md5(archive.read("cards.json"))
    return FetchResult(
        payload=payload,
        doc=doc,
        path=Path(path),
        json_md5=json_md5,
        source_version=datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d"),
    )


def _text_of(record: dict[str, Any], key: str) -> str:
    return (record.get("text") or {}).get(key, "") or ""


def _names_of(record: dict[str, Any]) -> list[tuple[str, str, str, int]]:
    """(lang, name, name_kind, is_primary) — primary name wins ties."""
    out: list[tuple[str, str, str, int]] = []
    sc = record.get("sc_name")
    md = record.get("md_name")
    cn = record.get("cn_name")

    if sc:
        out.append(("zh", sc, "official", 1))
    elif cn:
        out.append(("zh", cn, "alias", 1))
    if md and md != sc:
        out.append(("zh", md, "localized", 0))
    if cn and cn != sc:
        out.append(("zh", cn, "alias", 0))
    for key in ("nwbbs_n", "cnocg_n"):
        value = record.get(key)
        if value and value not in {sc, md, cn}:
            out.append(("zh", value, "alias", 0))
    return out


def apply_chinese_text(
    conn: sqlite3.Connection,
    doc: dict[str, Any],
    *,
    source_version: str | None = None,
    file_path: str | None = None,
    uri: str = CARDS_URL,
) -> ApplyResult:
    """Attach Chinese text / names / cid to cards already in the database."""
    result = ApplyResult(records=len(doc))
    now = datetime.now().isoformat(timespec="seconds")

    source_id = register_raw_source(
        conn,
        source_name=SOURCE_NAME,
        source_version=source_version,
        uri=uri,
        file_path=file_path,
        content_sha256=None,
        payload_bytes=None,
        record_count=len(doc),
        notes="ygocdb cards.zip (Simplified Chinese text + names)",
    )

    passcode_to_card = {
        row["external_id"]: int(row["card_id"])
        for row in conn.execute(
            "SELECT external_id, card_id FROM external_id WHERE source = 'ygopro_passcode'"
        )
    }

    with conn:
        for cid, record in doc.items():
            passcode = record.get("id")
            if not passcode:
                result.without_passcode += 1
                continue
            card_id = passcode_to_card.get(str(passcode))
            if card_id is None:
                result.unmatched += 1
                continue
            result.matched += 1

            texts = [
                ("effect", _text_of(record, "desc")),
                ("pendulum", _text_of(record, "pdesc")),
                ("types", _text_of(record, "types")),
            ]
            for kind, text in texts:
                if not text.strip():
                    continue
                conn.execute(
                    """
                    INSERT INTO card_text (card_id, lang, kind, source, text, text_sha256, updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT (card_id, lang, kind, source) DO UPDATE SET
                        text = excluded.text,
                        text_sha256 = excluded.text_sha256,
                        updated_at = excluded.updated_at
                    """,
                    (card_id, "zh", kind, SOURCE_NAME, text, sha256_text(text), now),
                )
                result.text_rows += 1

            for lang, name, kind, is_primary in _names_of(record):
                conn.execute(
                    """
                    INSERT INTO card_name (card_id, lang, name, name_kind, is_primary)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT (card_id, lang, name_kind, name) DO UPDATE SET
                        is_primary = excluded.is_primary
                    """,
                    (card_id, lang, name, kind, is_primary),
                )
                result.name_rows += 1

            conn.execute(
                "INSERT OR IGNORE INTO external_id (card_id, source, external_id) VALUES (?,?,?)",
                (card_id, "konami_cid", str(cid)),
            )
            result.cid_rows += 1

    return result
