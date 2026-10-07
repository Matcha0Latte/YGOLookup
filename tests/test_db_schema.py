import sqlite3

import pytest

from ygolookup.db.connection import connect
from ygolookup.db.migrations import MigrationError, apply_migrations, discover_migrations

EXPECTED_TABLES = {
    "schema_migrations",
    "raw_source",
    "raw_card_record",
    "card",
    "card_name",
    "external_id",
    "card_archetype",
    "card_flag",
}


def test_migrations_discover_in_order():
    versions = [v for v, _, _ in discover_migrations()]
    assert versions == sorted(versions)
    assert versions, "no migrations found"


def test_apply_migrations_creates_expected_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    conn.row_factory = sqlite3.Row
    applied = apply_migrations(conn)
    assert applied, "first run should apply at least one migration"

    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables
    conn.close()


def test_apply_migrations_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "s.db")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    """Orphan rows must be rejected — enforced via the shared connect() helper."""
    conn = connect(tmp_path / "s.db")
    apply_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO card_name (card_id, lang, name) VALUES (999999, 'en', 'ghost')")
    conn.close()


def test_connect_enables_foreign_keys(tmp_path):
    conn = connect(tmp_path / "s.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_migration_filename_contract(tmp_path):
    (tmp_path / "bad-name.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError):
        discover_migrations(tmp_path)
