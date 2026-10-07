from ygolookup.config import Config, PROJECT_ROOT


def test_project_root_points_at_repo():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()


def test_relative_paths_resolve_against_root():
    cfg = Config.from_env(PROJECT_ROOT)
    assert cfg.db_path.is_absolute()
    assert cfg.raw_dir.is_absolute()


def test_env_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("YGO_DB_PATH", str(tmp_path / "custom.db"))
    cfg = Config.from_env(PROJECT_ROOT)
    assert cfg.db_path == tmp_path / "custom.db"


def test_empty_embedding_model_is_valid():
    """Semantic layer must degrade gracefully when no model is configured."""
    cfg = Config.from_env(PROJECT_ROOT)
    assert isinstance(cfg.embedding_model, str)
