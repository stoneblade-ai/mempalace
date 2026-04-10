"""Tests for team config section in CortexConfig."""
import json
import pytest
from cortex.config import CortexConfig


def test_team_config_disabled_by_default(tmp_path):
    """No team section = team disabled."""
    config_dir = tmp_path / ".cortex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"cortex_path": str(tmp_path / "cortex")}))
    cfg = CortexConfig(config_dir=str(config_dir))
    assert cfg.team_enabled is False
    assert cfg.team_server is None
    assert cfg.team_api_key is None
    assert cfg.team_timeout == 3


def test_team_config_from_file(tmp_path):
    """Team section in config.json is parsed."""
    config_dir = tmp_path / ".cortex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "cortex_path": str(tmp_path / "cortex"),
        "team": {
            "enabled": True,
            "server": "https://team.example.com",
            "api_key": "ak_abc123",
            "timeout_seconds": 5,
        },
    }))
    cfg = CortexConfig(config_dir=str(config_dir))
    assert cfg.team_enabled is True
    assert cfg.team_server == "https://team.example.com"
    assert cfg.team_api_key == "ak_abc123"
    assert cfg.team_timeout == 5


def test_team_api_key_env_var_overrides_config(tmp_path, monkeypatch):
    """CORTEX_TEAM_API_KEY env var takes precedence over config.json."""
    config_dir = tmp_path / ".cortex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "cortex_path": str(tmp_path / "cortex"),
        "team": {
            "enabled": True,
            "server": "https://team.example.com",
            "api_key": "ak_from_config",
        },
    }))
    monkeypatch.setenv("CORTEX_TEAM_API_KEY", "ak_from_env")
    cfg = CortexConfig(config_dir=str(config_dir))
    assert cfg.team_api_key == "ak_from_env"
