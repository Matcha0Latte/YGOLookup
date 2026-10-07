"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep tests away from the developer's real database before importing anything.
os.environ.setdefault("YGO_DB_PATH", str(Path(__file__).resolve().parent / ".tmp" / "test.db"))
os.environ.setdefault("YGO_RAW_DIR", str(Path(__file__).resolve().parent / ".tmp" / "raw"))

from ygolookup.config import Config, PROJECT_ROOT  # noqa: E402


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
