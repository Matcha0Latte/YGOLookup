"""High-level ingest entry points used by the CLI and by tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db.models import CardRecord
from .normalize import normalize_cdb_row
from .pipeline import IngestResult, ingest_records
from .ygopro import iter_cdb_rows
from .ygopro import ygoprodeck as ypd
from . import ygocdb


def source_version_for_cdb(path: Path) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def ingest_from_cdb(conn: sqlite3.Connection, cdb_path: str | Path) -> IngestResult:
    """Import a native YGOPro / Project Ignis `cards.cdb`."""
    path = Path(cdb_path)
    rows = list(iter_cdb_rows(path))
    records: list[CardRecord] = []
    for row in rows:
        try:
            records.append(normalize_cdb_row(row))
        except ValueError as exc:
            print(f"[ingest] skip id={row.get('id')}: {exc}")

    return ingest_records(
        conn,
        records,
        source_name="ygopro_cdb",
        source_version=source_version_for_cdb(path),
        file_path=str(path),
        content_sha256=None,
        payload_bytes=path.stat().st_size,
        notes=f"cards.cdb imported from {path.name}",
    )


def ingest_from_ygoprodeck(
    conn: sqlite3.Connection,
    *,
    url: str,
    raw_dir: Path,
    local_path: str | Path | None = None,
) -> IngestResult:
    """Import the YGOProDeck JSON dump (downloads unless `local_path` is given)."""
    if local_path:
        fetched = ypd.load_local(Path(local_path))
    else:
        fetched = ypd.fetch(url, raw_dir)

    records = ypd.iter_card_records(fetched.records)
    return ingest_records(
        conn,
        records,
        source_name="ygoprodeck_json",
        source_version=fetched.source_version,
        uri=url,
        file_path=str(fetched.path),
        content_sha256=fetched.sha256,
        payload_bytes=len(fetched.payload),
        notes="YGOProDeck cardinfo dump",
    )


def apply_ygocdb_text(
    conn: sqlite3.Connection,
    *,
    raw_dir: Path,
    local_path: str | Path | None = None,
) -> ygocdb.ApplyResult:
    """Attach Simplified Chinese text and names from ygocdb.

    This is an enrichment pass: cards must already exist (imported from
    YGOProDeck or cards.cdb). Records are joined on the 8-digit passcode.
    """
    fetched = (
        ygocdb.load_local(local_path)
        if local_path
        else ygocdb.fetch(raw_dir=raw_dir)
    )
    return ygocdb.apply_chinese_text(
        conn,
        fetched.doc,
        source_version=fetched.source_version,
        file_path=str(fetched.path),
    )
