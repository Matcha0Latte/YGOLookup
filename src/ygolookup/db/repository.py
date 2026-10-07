"""Card read/write repository.

This is the only module that writes canonical card rows. Keeping writes here
means the ingest layer never hand-rolls SQL and the retrieval layer stays
read-only.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .models import CardRecord


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def find_card_by_external_id(conn: sqlite3.Connection, source: str, value: str) -> int | None:
    row = conn.execute(
        "SELECT card_id FROM external_id WHERE source = ? AND external_id = ?",
        (source, value),
    ).fetchone()
    return int(row["card_id"]) if row else None


def find_card_by_identity_key(conn: sqlite3.Connection, identity_key: str) -> int | None:
    """Resolve an identity key of the form 'passcode:123' or 'name:en:foo'."""
    kind, _, value = identity_key.partition(":")
    if kind == "passcode":
        return find_card_by_external_id(conn, "ygopro_passcode", value)
    return None


def upsert_card(conn: sqlite3.Connection, record: CardRecord, *, source_id: int | None = None) -> int:
    """Insert or update a canonical card. Returns the internal card_id."""
    card_id = None
    for ext in record.external_ids:
        card_id = find_card_by_external_id(conn, ext.source, ext.value)
        if card_id is not None:
            break
    if card_id is None:
        card_id = find_card_by_identity_key(conn, record.identity_key)

    now = _now()
    if card_id is None:
        cur = conn.execute(
            """
            INSERT INTO card (
                canonical_name, card_category, sub_category, race, attribute,
                level_rank, link_rating, pendulum_scale, atk, def,
                type_mask, race_mask, attribute_mask, category_mask, setcode_mask,
                alias_passcode, text_lang, raw_text, primary_source_id,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record.canonical_name,
                record.card_category,
                record.sub_category,
                record.race,
                record.attribute,
                record.level_rank,
                record.link_rating,
                record.pendulum_scale,
                record.atk,
                record.defense,
                record.type_mask,
                record.race_mask,
                record.attribute_mask,
                record.category_mask,
                record.setcode_mask,
                record.alias_passcode,
                record.text_lang,
                record.raw_text,
                source_id,
                now,
                now,
            ),
        )
        card_id = int(cur.lastrowid)
    else:
        conn.execute(
            """
            UPDATE card SET
                canonical_name = ?, card_category = ?, sub_category = ?,
                race = ?, attribute = ?, level_rank = ?, link_rating = ?,
                pendulum_scale = ?, atk = ?, def = ?,
                type_mask = COALESCE(?, type_mask),
                race_mask = COALESCE(?, race_mask),
                attribute_mask = COALESCE(?, attribute_mask),
                category_mask = COALESCE(?, category_mask),
                setcode_mask = COALESCE(?, setcode_mask),
                alias_passcode = COALESCE(?, alias_passcode),
                text_lang = ?, raw_text = ?,
                primary_source_id = COALESCE(?, primary_source_id),
                updated_at = ?
            WHERE card_id = ?
            """,
            (
                record.canonical_name,
                record.card_category,
                record.sub_category,
                record.race,
                record.attribute,
                record.level_rank,
                record.link_rating,
                record.pendulum_scale,
                record.atk,
                record.defense,
                record.type_mask,
                record.race_mask,
                record.attribute_mask,
                record.category_mask,
                record.setcode_mask,
                record.alias_passcode,
                record.text_lang,
                record.raw_text,
                source_id,
                now,
                card_id,
            ),
        )

    _replace_children(conn, card_id, record)
    return card_id


def _replace_children(conn: sqlite3.Connection, card_id: int, record: CardRecord) -> None:
    conn.execute("DELETE FROM card_name WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO card_name (card_id, lang, name, name_kind, is_primary) VALUES (?,?,?,?,?)",
        [(card_id, n.lang, n.name, n.kind, int(n.is_primary)) for n in record.names],
    )

    conn.executemany(
        "INSERT OR IGNORE INTO external_id (card_id, source, external_id) VALUES (?,?,?)",
        [(card_id, e.source, e.value) for e in record.external_ids],
    )

    conn.execute("DELETE FROM card_archetype WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO card_archetype (card_id, archetype, archetype_raw) VALUES (?,?,?)",
        [(card_id, slug, raw) for slug, raw in record.archetypes],
    )

    conn.execute("DELETE FROM card_flag WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO card_flag (card_id, flag) VALUES (?,?)",
        [(card_id, flag) for flag in sorted(record.flags)],
    )


# ---------------------------------------------------------------------- reads
def get_card(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM card WHERE card_id = ?", (card_id,)).fetchone()


def find_card_by_name(conn: sqlite3.Connection, name: str, *, exact: bool = True) -> sqlite3.Row | None:
    if exact:
        return conn.execute(
            "SELECT c.* FROM card c JOIN card_name n ON n.card_id = c.card_id"
            " WHERE n.name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
    return conn.execute(
        "SELECT c.* FROM card c JOIN card_name n ON n.card_id = c.card_id"
        " WHERE n.name LIKE ? COLLATE NOCASE LIMIT 1",
        (f"%{name}%",),
    ).fetchone()


def card_names(conn: sqlite3.Connection, card_id: int) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM card_name WHERE card_id = ?", (card_id,))]


def card_archetypes(conn: sqlite3.Connection, card_id: int) -> list[str]:
    return [
        r["archetype"]
        for r in conn.execute("SELECT archetype FROM card_archetype WHERE card_id = ?", (card_id,))
    ]


def card_flags(conn: sqlite3.Connection, card_id: int) -> list[str]:
    return [r["flag"] for r in conn.execute("SELECT flag FROM card_flag WHERE card_id = ?", (card_id,))]


def card_external_ids(conn: sqlite3.Connection, card_id: int) -> list[tuple[str, str]]:
    return [
        (r["source"], r["external_id"])
        for r in conn.execute("SELECT source, external_id FROM external_id WHERE card_id = ?", (card_id,))
    ]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def count(sql: str, args: tuple = ()) -> int:
        return int(conn.execute(sql, args).fetchone()[0])

    return {
        "cards": count("SELECT COUNT(*) FROM card"),
        "monsters": count("SELECT COUNT(*) FROM card WHERE card_category = 'MONSTER'"),
        "spells": count("SELECT COUNT(*) FROM card WHERE card_category = 'SPELL'"),
        "traps": count("SELECT COUNT(*) FROM card WHERE card_category = 'TRAP'"),
        "names": count("SELECT COUNT(*) FROM card_name"),
        "external_ids": count("SELECT COUNT(*) FROM external_id"),
        "archetypes": count("SELECT COUNT(DISTINCT archetype) FROM card_archetype"),
        "raw_sources": count("SELECT COUNT(*) FROM raw_source"),
        "raw_card_records": count("SELECT COUNT(*) FROM raw_card_record"),
    }
