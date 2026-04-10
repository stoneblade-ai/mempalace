"""Tests for team API key auth: hashing, generation, user lookup."""

from cortex.team_auth import hash_api_key, generate_api_key, resolve_user, check_wing_permission


def test_hash_api_key_deterministic():
    assert hash_api_key("ak_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5") == hash_api_key(
        "ak_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
    )


def test_hash_api_key_is_sha256():
    h = hash_api_key("ak_test123")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("ak_")
    hex_part = key[3:]
    assert len(hex_part) == 32
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_generate_api_key_unique():
    assert generate_api_key() != generate_api_key()


def test_resolve_user_found():
    key = "ak_testkey123"
    key_hash = hash_api_key(key)
    users = {key_hash: {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}}}
    user = resolve_user(key, users)
    assert user["user_id"] == "andy"
    assert user["role"] == "admin"


def test_resolve_user_not_found():
    assert resolve_user("ak_unknown", {}) is None


def test_check_wing_permission_admin():
    user = {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}}
    assert check_wing_permission(user, "wing_frontend", "read") is True
    assert check_wing_permission(user, "wing_anything", "write") is True


def test_check_wing_permission_member_read():
    user = {
        "user_id": "kai",
        "role": "member",
        "wings": {"read": ["wing_frontend", "wing_shared"], "write": ["wing_frontend"]},
    }
    assert check_wing_permission(user, "wing_frontend", "read") is True
    assert check_wing_permission(user, "wing_shared", "read") is True
    assert check_wing_permission(user, "wing_backend", "read") is False


def test_check_wing_permission_member_write():
    user = {
        "user_id": "kai",
        "role": "member",
        "wings": {"read": ["wing_frontend", "wing_shared"], "write": ["wing_frontend"]},
    }
    assert check_wing_permission(user, "wing_frontend", "write") is True
    assert check_wing_permission(user, "wing_shared", "write") is False
