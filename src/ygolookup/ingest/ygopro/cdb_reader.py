"""Reader for the native YGOPro / Project Ignis `cards.cdb` database.

A `cards.cdb` is a SQLite file with two tables:

    texts(id, name, desc, str1 .. str16)
    datas(id, ot, alias, setcode, type, atk, def, level, race, attribute, category)

This reader only extracts the upstream rows verbatim. Normalization happens in
`ingest/normalize.py`, so a malformed row can be inspected later from
`raw_card_record`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

TEXT_COLUMNS = ("name", "desc") + tuple(f"str{i}" for i in range(1, 17))
DATA_COLUMNS = ("ot", "alias", "setcode", "type", "atk", "def", "level", "race", "attribute", "category")


class CdbFormatError(RuntimeError):
    pass


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def validate_cdb(path: str | Path) -> None:
    path = Path(path)
    if not path.is_file():
        raise CdbFormatError(f"cards.cdb not found: {path}")
    conn = _open(path)
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = {"texts", "datas"} - tables
        if missing:
            raise CdbFormatError(f"{path} is missing table(s): {sorted(missing)}")
    finally:
        conn.close()


def iter_cdb_rows(path: str | Path) -> Iterator[dict]:
    """Yield one merged dict per upstream card id, values kept verbatim."""
    validate_cdb(path)
    conn = _open(Path(path))
    try:
        texts = {int(r["id"]): dict(r) for r in conn.execute("SELECT * FROM texts")}
        datas_rows = conn.execute("SELECT * FROM datas").fetchall()
    finally:
        conn.close()

    for row in datas_rows:
        row = dict(row)
        card_id = int(row["id"])
        text = texts.get(card_id, {})
        yield {
            "id": card_id,
            "name": text.get("name") or "",
            "desc": text.get("desc") or "",
            "strings": {col: text.get(col) or "" for col in TEXT_COLUMNS[2:]},
            "ot": row.get("ot"),
            "alias": row.get("alias"),
            "setcode": row.get("setcode"),
            "type": row.get("type"),
            "atk": row.get("atk"),
            "def": row.get("def"),
            "level": row.get("level"),
            "race": row.get("race"),
            "attribute": row.get("attribute"),
            "category": row.get("category"),
        }
