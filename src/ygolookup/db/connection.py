"""SQLite connection helpers.

SQLite is the source of truth for this project, so connection setup lives in
one place: pragmas, row factory, foreign keys.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str | Path, *, check_same_thread: bool = False) -> sqlite3.Connection:
    """Open (creating parent dirs) a SQLite connection with sane defaults."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
