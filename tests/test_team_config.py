"""Tests for team server configuration: load, save, user CRUD."""
import json
import pytest
from cortex.team_config import TeamServerConfig
from cortex.team_auth import hash_api_key


def test_load_empty_config(tmp_path):
    cfg = TeamServerConfig(config_path=str(tmp_path / "team_config.json"))
    assert cfg.users == {}


def test_load_existing_config(tmp_path):
    config_path = tmp_path / "team_config.json"
    data = {"users": {"hash_1": {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}}}}
    config_path.write_text(json.dumps(data))
    cfg = TeamServerConfig(config_path=str(config_path))
    assert "hash_1" in cfg.users
    assert cfg.users["hash_1"]["user_id"] == "andy"


def test_add_user(tmp_path):
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    api_key = cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend", "wing_shared"], write_wings=["wing_frontend"])
    assert api_key.startswith("ak_")
    key_hash = hash_api_key(api_key)
    assert key_hash in cfg.users
    assert cfg.users[key_hash]["user_id"] == "kai"
    assert cfg.users[key_hash]["role"] == "member"
    assert cfg.users[key_hash]["wings"]["read"] == ["wing_frontend", "wing_shared"]
    assert cfg.users[key_hash]["wings"]["write"] == ["wing_frontend"]
    saved = json.loads(config_path.read_text())
    assert key_hash in saved["users"]


def test_remove_user(tmp_path):
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    cfg.remove_user("kai")
    assert all(u["user_id"] != "kai" for u in cfg.users.values())


def test_remove_user_not_found(tmp_path):
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    with pytest.raises(ValueError, match="not found"):
        cfg.remove_user("nobody")


def test_rotate_key(tmp_path):
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    old_key = cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    new_key = cfg.rotate_key("kai")
    assert new_key != old_key
    old_hash = hash_api_key(old_key)
    new_hash = hash_api_key(new_key)
    assert new_hash in cfg.users
    assert old_hash in cfg.users
    assert "grace_expires" in cfg.users[old_hash]


def test_get_user_by_id(tmp_path):
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    user = cfg.get_user_by_id("kai")
    assert user is not None
    assert user["user_id"] == "kai"
    assert cfg.get_user_by_id("nobody") is None
