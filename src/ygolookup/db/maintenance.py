"""Database maintenance helpers.

Query plans for the effect tables are sensitive to table statistics; running
ANALYZE after a bulk rebuild keeps the planner honest.
"""

from __future__ import annotations

import sqlite3


def analyze(conn: sqlite3.Connection) -> None:
    conn.execute("ANALYZE")


def integrity_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
