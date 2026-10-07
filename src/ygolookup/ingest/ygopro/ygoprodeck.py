"""YGOProDeck JSON source adapter.

YGOProDeck mirrors the same card pool that ships with YGOPro / EDOPro and
exposes it as a single JSON document, which makes it a convenient bootstrap
source while a local `cards.cdb` is unavailable.

The fetched payload is written to `data/raw` unmodified before any parsing, so
the import can always be reproduced offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ...db.models import CardRecord
from ..normalize import normalize_ygoprodeck_record
from ..pipeline import sha256_bytes, snapshot_raw

DEFAULT_TIMEOUT = 60


@dataclass
class FetchResult:
    payload: bytes
    records: list[dict[str, Any]]
    path: Path
    sha256: str
    source_version: str


def fetch(url: str, raw_dir: Path, *, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    request = Request(url, headers={"User-Agent": "YGOLookup/0.1 (+local research tool)"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        payload = response.read()

    digest = sha256_bytes(payload)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = snapshot_raw(payload, raw_dir, f"ygoprodeck-{stamp}-{digest[:8]}.json")
    document = json.loads(payload.decode("utf-8"))
    records = document["data"] if isinstance(document, dict) else document
    return FetchResult(
        payload=payload,
        records=records,
        path=path,
        sha256=digest,
        source_version=datetime.now().strftime("%Y-%m-%d"),
    )


def load_local(path: Path) -> FetchResult:
    """Import from an already-downloaded snapshot (offline path)."""
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    records = document["data"] if isinstance(document, dict) else document
    return FetchResult(
        payload=payload,
        records=records,
        path=path,
        sha256=sha256_bytes(payload),
        source_version=datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
    )


def iter_card_records(records: list[dict[str, Any]]) -> list[CardRecord]:
    out: list[CardRecord] = []
    for raw in records:
        try:
            out.append(normalize_ygoprodeck_record(raw))
        except ValueError as exc:
            # A single malformed upstream record must not kill the whole import.
            print(f"[ingest] skip {raw.get('name')!r}: {exc}")
    return out
