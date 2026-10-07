"""Ingest pipeline: raw snapshot -> raw_source row -> canonical cards.

Every run is idempotent: re-importing the same payload updates existing cards
in place instead of creating duplicates.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from ..db.models import CardRecord
from ..db.repository import upsert_card
from .id_mapping import IdentityIndex


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def snapshot_raw(payload: bytes, raw_dir: Path, filename: str) -> Path:
    """Persist an immutable copy of the upstream payload under data/raw."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / filename
    path.write_bytes(payload)
    return path


def register_raw_source(
    conn: sqlite3.Connection,
    *,
    source_name: str,
    source_version: str | None = None,
    uri: str | None = None,
    file_path: str | None = None,
    content_sha256: str | None = None,
    payload_bytes: int | None = None,
    record_count: int | None = None,
    notes: str | None = None,
) -> int:
    cur = conn.execute("SELECT source_id FROM raw_source WHERE source_name = ? AND content_sha256 IS ?",
                       (source_name, content_sha256))
    row = cur.fetchone()
    if row:
        return int(row["source_id"])

    cur = conn.execute(
        """
        INSERT INTO raw_source (source_name, source_version, uri, file_path, content_sha256,
                                payload_bytes, record_count, fetched_at, notes)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            source_name,
            source_version,
            uri,
            file_path,
            content_sha256,
            payload_bytes,
            record_count,
            datetime.now().isoformat(timespec="seconds"),
            notes,
        ),
    )
    return int(cur.lastrowid)


def insert_raw_card_record(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    external_id: str | None,
    payload: dict,
) -> int:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cur = conn.execute(
        "INSERT INTO raw_card_record (source_id, external_id, payload_sha256, payload_json) VALUES (?,?,?,?)",
        (source_id, external_id, sha256_text(blob), blob),
    )
    return int(cur.lastrowid)


@dataclass
class IngestResult:
    source_id: int
    records_seen: int = 0
    cards_upserted: int = 0
    cards_created: int = 0
    cards_updated: int = 0
    collisions: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "records_seen": self.records_seen,
            "cards_upserted": self.cards_upserted,
            "cards_created": self.cards_created,
            "cards_updated": self.cards_updated,
            "collisions": self.collisions,
            "errors": self.errors[:20],
        }


def ingest_records(
    conn: sqlite3.Connection,
    records: Iterable[CardRecord],
    *,
    source_name: str,
    source_version: str | None = None,
    uri: str | None = None,
    file_path: str | None = None,
    content_sha256: str | None = None,
    payload_bytes: int | None = None,
    notes: str | None = None,
) -> IngestResult:
    """Write raw records + canonical cards. Safe to run repeatedly."""
    records = list(records)
    index = IdentityIndex()
    index.extend(records)
    groups = index.finalize()

    source_id = register_raw_source(
        conn,
        source_name=source_name,
        source_version=source_version,
        uri=uri,
        file_path=file_path,
        content_sha256=content_sha256,
        payload_bytes=payload_bytes,
        record_count=len(records),
        notes=notes,
    )

    result = IngestResult(source_id=source_id, records_seen=len(records), collisions=index.collisions)

    with conn:
        for record in records:
            try:
                external_id = record.external_id("ygopro_passcode") or record.external_id("ygoprodeck_id")
                raw_id = insert_raw_card_record(
                    conn,
                    source_id=source_id,
                    external_id=external_id,
                    payload=_record_payload(record),
                )
                before = _card_exists(conn, record)
                card_id = upsert_card(conn, record, source_id=source_id)
                conn.execute("UPDATE raw_card_record SET card_id = ? WHERE raw_id = ?", (card_id, raw_id))
                if before:
                    result.cards_updated += 1
                else:
                    result.cards_created += 1
                result.cards_upserted += 1
            except Exception as exc:  # keep ingesting; report at the end
                result.errors.append(f"{record.canonical_name}: {exc}")

    return result


def _card_exists(conn: sqlite3.Connection, record: CardRecord) -> bool:
    for ext in record.external_ids:
        row = conn.execute(
            "SELECT 1 FROM external_id WHERE source = ? AND external_id = ?",
            (ext.source, ext.value),
        ).fetchone()
        if row:
            return True
    return False


def _record_payload(record: CardRecord) -> dict:
    """JSON view of the normalized record, stored for auditability."""
    return {
        "canonical_name": record.canonical_name,
        "card_category": record.card_category,
        "sub_category": record.sub_category,
        "race": record.race,
        "attribute": record.attribute,
        "level_rank": record.level_rank,
        "link_rating": record.link_rating,
        "pendulum_scale": record.pendulum_scale,
        "atk": record.atk,
        "def": record.defense,
        "masks": {
            "type": record.type_mask,
            "race": record.race_mask,
            "attribute": record.attribute_mask,
            "category": record.category_mask,
            "setcode": record.setcode_mask,
        },
        "alias_passcode": record.alias_passcode,
        "external_ids": [{"source": e.source, "value": e.value} for e in record.external_ids],
        "archetypes": [{"slug": s, "raw": r} for s, r in record.archetypes],
        "flags": sorted(record.flags),
        "raw_text": record.raw_text,
    }


def iter_raw_records(conn: sqlite3.Connection, source_id: int) -> Iterator[dict]:
    """Re-read previously stored raw records (used to re-parse without network)."""
    for row in conn.execute(
        "SELECT payload_json FROM raw_card_record WHERE source_id = ? ORDER BY raw_id",
        (source_id,),
    ):
        yield json.loads(row["payload_json"])
