"""Minimal forward-only SQL migration runner.

Migrations are plain `.sql` files in `db/migrations/`, ordered by their numeric
prefix. Each is applied once, inside a transaction, and recorded in
`schema_migrations`.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_FILENAME_RE = re.compile(r"^(\d+)_(.+)\.sql$")


class MigrationError(RuntimeError):
    pass


def discover_migrations(directory: Path | None = None) -> list[tuple[int, str, Path]]:
    directory = directory or MIGRATIONS_DIR
    found: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        m = _FILENAME_RE.match(path.name)
        if not m:
            raise MigrationError(f"migration filename must be '<n>_<name>.sql': {path.name}")
        found.append((int(m.group(1)), m.group(2), path))
    found.sort(key=lambda item: item[0])

    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise MigrationError(f"duplicate migration versions: {versions}")
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    return {int(r["version"]) for r in conn.execute("SELECT version FROM schema_migrations")}


def apply_migrations(conn: sqlite3.Connection, directory: Path | None = None) -> list[int]:
    """Apply all pending migrations. Returns the versions applied this call."""
    done = applied_versions(conn)
    applied: list[int] = []
    for version, name, path in discover_migrations(directory):
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with conn:  # commit on success, rollback on error
                conn.executescript(script)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, now),
                )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise MigrationError(f"migration {path.name} failed: {exc}") from exc
        applied.append(version)
    return applied
