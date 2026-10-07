"""Shared pytest fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Keep tests away from the developer's real database before importing anything.
os.environ.setdefault("YGO_DB_PATH", str(Path(__file__).resolve().parent / ".tmp" / "test.db"))
os.environ.setdefault("YGO_RAW_DIR", str(Path(__file__).resolve().parent / ".tmp" / "raw"))

from ygolookup.config import Config, PROJECT_ROOT  # noqa: E402
from ygolookup.ingest.normalize import normalize_ygoprodeck_record  # noqa: E402
from ygolookup.ingest.pipeline import ingest_records  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "search_fixture.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return PROJECT_ROOT / "tests" / ".tmp"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        db_path=tmp_path / "test.db",
        raw_dir=tmp_path / "raw",
        ygoprodeck_api="",
        embedding_model="",
    )


def load_fixture_pool(conn, *, source_name: str = "test_fixture", source_version: str = "1") -> None:
    """Ingest the shared card pool *and* its Chinese text into `conn`.

    The effect parser reads Simplified Chinese, so a pool without `zh_desc`
    rows produces zero effects. Tests that only exercise card properties can
    skip this by ingesting records directly.
    """
    ingest_records(
        conn,
        [normalize_ygoprodeck_record(raw) for raw in RAW],
        source_name=source_name,
        source_version=source_version,
    )
    for raw in RAW:
        row = conn.execute(
            "SELECT card_id FROM external_id WHERE source = 'ygopro_passcode' AND external_id = ?",
            (str(raw["id"]),),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO card_text"
            " (card_id, lang, kind, source, text, text_sha256, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (row["card_id"], "zh", "effect", source_name, raw["zh_desc"], "0", "2026-01-01T00:00:00"),
        )
    conn.commit()
