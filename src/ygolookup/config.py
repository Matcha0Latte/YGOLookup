"""Environment / path configuration.

No third-party dependency: `.env` is parsed by hand so the runtime stays
standard-library only. Secrets are never echoed by any CLI command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repository root = two levels up from src/ygolookup/config.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = "data/processed/ygolookup.db"
DEFAULT_RAW_DIR = "data/raw"
DEFAULT_YGOPRODECK_API = "https://db.ygoprodeck.com/api/v7/cardinfo.php"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. Existing process env always wins."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    db_path: Path
    raw_dir: Path
    ygoprodeck_api: str
    embedding_model: str

    @classmethod
    def from_env(cls, root: Path | None = None) -> "Config":
        root = root or PROJECT_ROOT
        _load_dotenv(root / ".env")

        def abs_path(value: str, default: str) -> Path:
            p = Path(value or default)
            return p if p.is_absolute() else (root / p)

        return cls(
            db_path=abs_path(os.environ.get("YGO_DB_PATH", ""), DEFAULT_DB_PATH),
            raw_dir=abs_path(os.environ.get("YGO_RAW_DIR", ""), DEFAULT_RAW_DIR),
            ygoprodeck_api=os.environ.get("YGO_YGOPRODECK_API") or DEFAULT_YGOPRODECK_API,
            embedding_model=os.environ.get("YGO_EMBEDDING_MODEL", ""),
        )


config = Config.from_env()
