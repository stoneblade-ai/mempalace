# Team Shared Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add team-shared memory to Cortex — a FastAPI team server, an HTTP client with routing layer in the MCP server, and CLI extensions for publish/team management.

**Architecture:** Three independent subsystems built in order: (1) Team Server — standalone FastAPI app with auth, CRUD, search, KG, and WAL; (2) TeamClient + Router — HTTP client in the MCP server that queries both local and team, merges via RRF; (3) CLI Extensions — `publish`, `team` subcommands, `--layer` flag on search.

**Tech Stack:** Python 3.9+, FastAPI, uvicorn, httpx (async HTTP client), ChromaDB, SQLite, existing cortex infrastructure.

**Spec:** `docs/superpowers/specs/2026-04-10-team-shared-memory-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `cortex/team_server.py` | FastAPI app: endpoints, auth middleware, permission checks, WAL logging |
| `cortex/team_auth.py` | API key hashing, user lookup, permission resolution, key generation/rotation |
| `cortex/team_config.py` | Team server config loading (`team_config.json`), user CRUD |
| `cortex/team_client.py` | Async HTTP client for talking to team server from local MCP |
| `cortex/team_router.py` | Routing layer: decides local/team/both, RRF merge, dedupe |
| `cortex/team_cli.py` | CLI subcommands: `team init/status/whoami/serve/add-user/remove-user/rotate-key` |
| `cortex/publish.py` | Publish logic: local→team, re-publish with version check, batch publish |
| `tests/test_team_auth.py` | Auth unit tests |
| `tests/test_team_config.py` | Team config unit tests |
| `tests/test_team_server.py` | Server endpoint integration tests |
| `tests/test_team_client.py` | Client unit tests (mocked HTTP) |
| `tests/test_team_router.py` | Router + RRF merge tests |
| `tests/test_publish.py` | Publish flow tests |
| `tests/test_team_cli.py` | CLI subcommand tests |

### Modified Files

| File | Changes |
|------|---------|
| `cortex/config.py` | Add `team` config section parsing, env var `CORTEX_TEAM_API_KEY` |
| `cortex/mcp_server.py` | Wire in team_router for search/status/wings/rooms/delete, add `cortex_publish` tool |
| `cortex/cli.py` | Add `publish` and `team` commands, `--layer` on search, `--publish` on mine |
| `pyproject.toml` | Add `fastapi`, `uvicorn`, `httpx` to optional `[team]` dependency group |

---

## Task 1: Dependencies and Config Extension

**Files:**
- Modify: `pyproject.toml`
- Modify: `cortex/config.py`
- Create: `tests/test_team_config_ext.py`

- [ ] **Step 1: Add team dependency group to pyproject.toml**

```toml
# Add after [project.optional-dependencies] spellcheck line
team = ["fastapi>=0.115.0", "uvicorn>=0.30.0", "httpx>=0.27.0"]
```

- [ ] **Step 2: Write failing test for team config parsing**

```python
# tests/test_team_config_ext.py
"""Tests for team config section in CortexConfig."""
import json
import pytest
from cortex.config import CortexConfig


def test_team_config_disabled_by_default(tmp_path):
    """No team section = team disabled."""
    config_dir = tmp_path / ".cortex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"palace_path": str(tmp_path / "palace")}))
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
        "palace_path": str(tmp_path / "palace"),
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
        "palace_path": str(tmp_path / "palace"),
        "team": {
            "enabled": True,
            "server": "https://team.example.com",
            "api_key": "ak_from_config",
        },
    }))
    monkeypatch.setenv("CORTEX_TEAM_API_KEY", "ak_from_env")
    cfg = CortexConfig(config_dir=str(config_dir))
    assert cfg.team_api_key == "ak_from_env"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_config_ext.py -v`
Expected: FAIL — `CortexConfig` has no `team_enabled` attribute

- [ ] **Step 4: Implement team config properties in config.py**

Add these properties to `CortexConfig` class after `hall_keywords`:

```python
@property
def team_enabled(self):
    """Whether team layer is enabled."""
    team = self._file_config.get("team", {})
    return bool(team.get("enabled", False))

@property
def team_server(self):
    """Team server URL."""
    team = self._file_config.get("team", {})
    return team.get("server")

@property
def team_api_key(self):
    """Team API key. Env var CORTEX_TEAM_API_KEY takes precedence."""
    env_val = os.environ.get("CORTEX_TEAM_API_KEY")
    if env_val:
        return env_val
    team = self._file_config.get("team", {})
    return team.get("api_key")

@property
def team_timeout(self):
    """Team server timeout in seconds."""
    team = self._file_config.get("team", {})
    return team.get("timeout_seconds", 3)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_config_ext.py -v`
Expected: 3 passed

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All existing tests pass

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml cortex/config.py tests/test_team_config_ext.py
git commit -m "feat(team): add team config section and dependency group"
```

---

## Task 2: Team Auth Module

**Files:**
- Create: `cortex/team_auth.py`
- Create: `tests/test_team_auth.py`

- [ ] **Step 1: Write failing tests for auth module**

```python
# tests/test_team_auth.py
"""Tests for team API key auth: hashing, generation, user lookup."""
import pytest
from cortex.team_auth import hash_api_key, generate_api_key, resolve_user, check_wing_permission


def test_hash_api_key_deterministic():
    """Same key always produces same hash."""
    key = "ak_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
    assert hash_api_key(key) == hash_api_key(key)


def test_hash_api_key_is_sha256():
    """Hash is a 64-char hex string (SHA-256)."""
    h = hash_api_key("ak_test123")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_generate_api_key_format():
    """Generated key starts with ak_ and has 32 hex chars."""
    key = generate_api_key()
    assert key.startswith("ak_")
    hex_part = key[3:]
    assert len(hex_part) == 32
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_generate_api_key_unique():
    """Two generated keys are different."""
    assert generate_api_key() != generate_api_key()


def test_resolve_user_found():
    """Resolve a known API key to its user config."""
    key = "ak_testkey123"
    key_hash = hash_api_key(key)
    users = {
        key_hash: {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}},
    }
    user = resolve_user(key, users)
    assert user["user_id"] == "andy"
    assert user["role"] == "admin"


def test_resolve_user_not_found():
    """Unknown key returns None."""
    users = {}
    assert resolve_user("ak_unknown", users) is None


def test_check_wing_permission_admin():
    """Admin can read and write any wing."""
    user = {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}}
    assert check_wing_permission(user, "wing_frontend", "read") is True
    assert check_wing_permission(user, "wing_anything", "write") is True


def test_check_wing_permission_member_read():
    """Member can read listed wings."""
    user = {
        "user_id": "kai",
        "role": "member",
        "wings": {"read": ["wing_frontend", "wing_shared"], "write": ["wing_frontend"]},
    }
    assert check_wing_permission(user, "wing_frontend", "read") is True
    assert check_wing_permission(user, "wing_shared", "read") is True
    assert check_wing_permission(user, "wing_backend", "read") is False


def test_check_wing_permission_member_write():
    """Member can only write to listed write wings."""
    user = {
        "user_id": "kai",
        "role": "member",
        "wings": {"read": ["wing_frontend", "wing_shared"], "write": ["wing_frontend"]},
    }
    assert check_wing_permission(user, "wing_frontend", "write") is True
    assert check_wing_permission(user, "wing_shared", "write") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cortex.team_auth'`

- [ ] **Step 3: Implement team_auth.py**

```python
# cortex/team_auth.py
"""Team API key authentication: generation, hashing, permission checks."""

import hashlib
import secrets


def generate_api_key() -> str:
    """Generate a new API key: ak_ + 32 random hex chars."""
    return f"ak_{secrets.token_hex(16)}"


def hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key. Used as lookup key in user config."""
    return hashlib.sha256(key.encode()).hexdigest()


def resolve_user(api_key: str, users: dict) -> dict | None:
    """Look up user config by API key hash.

    Args:
        api_key: Raw API key from request header.
        users: Dict mapping key hashes to user configs.

    Returns:
        User config dict or None if key not found.
    """
    key_hash = hash_api_key(api_key)
    return users.get(key_hash)


def check_wing_permission(user: dict, wing: str, operation: str) -> bool:
    """Check if user has permission for operation on wing.

    Args:
        user: User config dict with role and wings.
        wing: Wing name to check.
        operation: "read" or "write".

    Returns:
        True if permitted.
    """
    wings_config = user.get("wings", {})
    allowed = wings_config.get(operation, [])
    if allowed == "*":
        return True
    return wing in allowed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_auth.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add cortex/team_auth.py tests/test_team_auth.py
git commit -m "feat(team): add auth module — key generation, hashing, permission checks"
```

---

## Task 3: Team Server Config Module

**Files:**
- Create: `cortex/team_config.py`
- Create: `tests/test_team_config.py`

- [ ] **Step 1: Write failing tests for team server config**

```python
# tests/test_team_config.py
"""Tests for team server configuration: load, save, user CRUD."""
import json
import pytest
from cortex.team_config import TeamServerConfig
from cortex.team_auth import hash_api_key


def test_load_empty_config(tmp_path):
    """No config file = empty users."""
    cfg = TeamServerConfig(config_path=str(tmp_path / "team_config.json"))
    assert cfg.users == {}


def test_load_existing_config(tmp_path):
    """Load users from existing config file."""
    config_path = tmp_path / "team_config.json"
    data = {
        "users": {
            "hash_1": {"user_id": "andy", "role": "admin", "wings": {"read": "*", "write": "*"}},
        }
    }
    config_path.write_text(json.dumps(data))
    cfg = TeamServerConfig(config_path=str(config_path))
    assert "hash_1" in cfg.users
    assert cfg.users["hash_1"]["user_id"] == "andy"


def test_add_user(tmp_path):
    """Add a new user, returns the generated API key."""
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    api_key = cfg.add_user(
        user_id="kai",
        role="member",
        read_wings=["wing_frontend", "wing_shared"],
        write_wings=["wing_frontend"],
    )
    assert api_key.startswith("ak_")
    # Verify user was stored by hash
    key_hash = hash_api_key(api_key)
    assert key_hash in cfg.users
    assert cfg.users[key_hash]["user_id"] == "kai"
    assert cfg.users[key_hash]["role"] == "member"
    assert cfg.users[key_hash]["wings"]["read"] == ["wing_frontend", "wing_shared"]
    assert cfg.users[key_hash]["wings"]["write"] == ["wing_frontend"]
    # Verify config file was written
    saved = json.loads(config_path.read_text())
    assert key_hash in saved["users"]


def test_remove_user(tmp_path):
    """Remove a user by user_id."""
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    api_key = cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    cfg.remove_user("kai")
    assert all(u["user_id"] != "kai" for u in cfg.users.values())


def test_remove_user_not_found(tmp_path):
    """Removing nonexistent user raises ValueError."""
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    with pytest.raises(ValueError, match="not found"):
        cfg.remove_user("nobody")


def test_rotate_key(tmp_path):
    """Rotate key: new key works, old key has grace period."""
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    old_key = cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    new_key = cfg.rotate_key("kai")
    assert new_key != old_key
    # Both old and new hashes should be in users
    old_hash = hash_api_key(old_key)
    new_hash = hash_api_key(new_key)
    assert new_hash in cfg.users
    assert old_hash in cfg.users
    # Old key entry should have a grace_expires field
    assert "grace_expires" in cfg.users[old_hash]


def test_get_user_by_id(tmp_path):
    """Look up user config by user_id."""
    config_path = tmp_path / "team_config.json"
    cfg = TeamServerConfig(config_path=str(config_path))
    cfg.add_user(user_id="kai", role="member", read_wings=["wing_frontend"], write_wings=[])
    user = cfg.get_user_by_id("kai")
    assert user is not None
    assert user["user_id"] == "kai"
    assert cfg.get_user_by_id("nobody") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement team_config.py**

```python
# cortex/team_config.py
"""Team server configuration: user management, persistence."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from .team_auth import generate_api_key, hash_api_key

GRACE_PERIOD_HOURS = 24


class TeamServerConfig:
    """Manages team_config.json: user CRUD, key rotation."""

    def __init__(self, config_path: str):
        self._config_path = Path(config_path)
        self._data = {"users": {}}
        if self._config_path.exists():
            try:
                self._data = json.loads(self._config_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {"users": {}}

    @property
    def users(self) -> dict:
        return self._data.get("users", {})

    def _save(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(self._data, indent=2))

    def add_user(
        self,
        user_id: str,
        role: str,
        read_wings: list[str],
        write_wings: list[str],
    ) -> str:
        """Add a user, generate and return their API key."""
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        self._data.setdefault("users", {})[key_hash] = {
            "user_id": user_id,
            "role": role,
            "wings": {"read": read_wings, "write": write_wings},
        }
        self._save()
        return api_key

    def remove_user(self, user_id: str):
        """Remove all key entries for a user_id."""
        users = self._data.get("users", {})
        to_remove = [h for h, u in users.items() if u["user_id"] == user_id]
        if not to_remove:
            raise ValueError(f"User '{user_id}' not found")
        for h in to_remove:
            del users[h]
        self._save()

    def rotate_key(self, user_id: str) -> str:
        """Generate new key for user. Old key gets 24h grace period."""
        users = self._data.get("users", {})
        # Find current (non-grace) entry
        current_hash = None
        current_config = None
        for h, u in users.items():
            if u["user_id"] == user_id and "grace_expires" not in u:
                current_hash = h
                current_config = u
                break
        if current_config is None:
            raise ValueError(f"User '{user_id}' not found")
        # Mark old key with grace period
        grace_expires = (datetime.now() + timedelta(hours=GRACE_PERIOD_HOURS)).isoformat()
        current_config["grace_expires"] = grace_expires
        # Generate new key with same permissions
        new_key = generate_api_key()
        new_hash = hash_api_key(new_key)
        users[new_hash] = {
            "user_id": current_config["user_id"],
            "role": current_config["role"],
            "wings": current_config["wings"],
        }
        self._save()
        return new_key

    def get_user_by_id(self, user_id: str) -> dict | None:
        """Find first non-grace user entry by user_id."""
        for u in self.users.values():
            if u["user_id"] == user_id and "grace_expires" not in u:
                return u
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_config.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add cortex/team_config.py tests/test_team_config.py
git commit -m "feat(team): add server config module — user CRUD, key rotation"
```

---

## Task 4: Team Server — Core Endpoints

**Files:**
- Create: `cortex/team_server.py`
- Create: `tests/test_team_server.py`

- [ ] **Step 1: Write failing tests for server health and auth**

```python
# tests/test_team_server.py
"""Integration tests for team server endpoints."""
import json
import pytest
from cortex.team_auth import hash_api_key

# Defer FastAPI import to avoid hard dependency
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from cortex.team_server import create_app


@pytest.fixture
def team_env(tmp_path):
    """Set up a team server with test config and ChromaDB."""
    config_path = tmp_path / "team_config.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    api_key = "ak_testkey_for_integration_tests00"
    key_hash = hash_api_key(api_key)
    config_path.write_text(json.dumps({
        "users": {
            key_hash: {
                "user_id": "tester",
                "role": "admin",
                "wings": {"read": "*", "write": "*"},
            }
        }
    }))
    app = create_app(config_path=str(config_path), data_dir=str(data_dir))
    client = TestClient(app)
    return {"client": client, "api_key": api_key, "data_dir": data_dir}


def test_health_no_auth(team_env):
    """GET /api/v1/health needs no auth."""
    resp = team_env["client"].get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_status_requires_auth(team_env):
    """GET /api/v1/status without key returns 401."""
    resp = team_env["client"].get("/api/v1/status")
    assert resp.status_code == 401


def test_status_with_auth(team_env):
    """GET /api/v1/status with valid key returns 200."""
    resp = team_env["client"].get(
        "/api/v1/status",
        headers={"X-API-Key": team_env["api_key"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data


def test_add_and_search_drawer(team_env):
    """POST drawer then search for it."""
    headers = {"X-API-Key": team_env["api_key"]}
    # Add a drawer
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test",
        "room": "room_decisions",
        "content": "We decided to use PostgreSQL for the team knowledge graph at scale.",
        "source_type": "direct",
    })
    assert resp.status_code == 201
    drawer_id = resp.json()["drawer_id"]
    assert drawer_id.startswith("team_")
    assert resp.json()["version"] == 1

    # Search for it
    resp = team_env["client"].post("/api/v1/search", headers=headers, json={
        "query": "PostgreSQL decision",
        "n_results": 5,
    })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert any("PostgreSQL" in r["content"] for r in results)


def test_update_drawer_with_version(team_env):
    """PATCH drawer requires correct version."""
    headers = {"X-API-Key": team_env["api_key"]}
    # Create
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "original", "source_type": "direct",
    })
    drawer_id = resp.json()["drawer_id"]
    # Update with correct version
    resp = team_env["client"].patch(
        f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "1"},
        json={"content": "updated content"},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    # Update with stale version -> 409
    resp = team_env["client"].patch(
        f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "1"},
        json={"content": "should fail"},
    )
    assert resp.status_code == 409


def test_delete_drawer_with_version(team_env):
    """DELETE requires correct version."""
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "to delete", "source_type": "direct",
    })
    drawer_id = resp.json()["drawer_id"]
    # Wrong version
    resp = team_env["client"].delete(
        f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "99"},
    )
    assert resp.status_code == 409
    # Correct version
    resp = team_env["client"].delete(
        f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "1"},
    )
    assert resp.status_code == 200


def test_permission_denied_wrong_wing(team_env):
    """Member without wing write access gets 403."""
    # Add a restricted user
    restricted_key = "ak_restricted_user_key_000000000"
    restricted_hash = hash_api_key(restricted_key)
    config_path = team_env["data_dir"].parent / "team_config.json"
    config = json.loads(config_path.read_text())
    config["users"][restricted_hash] = {
        "user_id": "kai",
        "role": "member",
        "wings": {"read": ["wing_frontend"], "write": ["wing_frontend"]},
    }
    config_path.write_text(json.dumps(config))

    resp = team_env["client"].post(
        "/api/v1/drawers",
        headers={"X-API-Key": restricted_key},
        json={"wing": "wing_backend", "room": "room_a", "content": "test", "source_type": "direct"},
    )
    assert resp.status_code == 403


def test_list_drawers(team_env):
    """GET /api/v1/drawers lists with filters."""
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "drawer A", "source_type": "direct",
    })
    team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_other", "room": "room_b", "content": "drawer B", "source_type": "direct",
    })
    # List all
    resp = team_env["client"].get("/api/v1/drawers", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["drawers"]) >= 2
    # Filter by wing
    resp = team_env["client"].get("/api/v1/drawers?wing=wing_test", headers=headers)
    assert all(d["wing"] == "wing_test" for d in resp.json()["drawers"])


def test_wings_and_taxonomy(team_env):
    """GET /api/v1/wings and /api/v1/taxonomy work."""
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "content", "source_type": "direct",
    })
    resp = team_env["client"].get("/api/v1/wings", headers=headers)
    assert resp.status_code == 200
    assert "wing_test" in resp.json()["wings"]

    resp = team_env["client"].get("/api/v1/taxonomy", headers=headers)
    assert resp.status_code == 200
    assert "wing_test" in resp.json()["taxonomy"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cortex.team_server'`

- [ ] **Step 3: Implement team_server.py**

```python
# cortex/team_server.py
"""Team memory server — FastAPI app with auth, CRUD, search, versioning."""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from .config import sanitize_name, sanitize_content
from .team_auth import resolve_user, check_wing_permission
from .team_config import TeamServerConfig
from .version import __version__

logger = logging.getLogger("cortex_team")


def create_app(config_path: str, data_dir: str):
    """Create the FastAPI app. Separate function for testability."""
    from fastapi import FastAPI, Request, Response, Header, Query
    from fastapi.responses import JSONResponse

    import chromadb

    app = FastAPI(title="Cortex Team Server", version=__version__)

    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    palace_path = data_path / "palace"
    palace_path.mkdir(exist_ok=True)
    wal_path = data_path / "wal"
    wal_path.mkdir(exist_ok=True)
    wal_file = wal_path / "write_log.jsonl"

    chroma_client = chromadb.PersistentClient(path=str(palace_path))
    collection = chroma_client.get_or_create_collection("cortex_team_drawers")

    # In-memory version store: drawer_id -> version int
    # Loaded from metadata on startup, updated on writes
    _versions: dict[str, int] = {}
    # In-memory drawer metadata store: drawer_id -> full metadata
    _metadata: dict[str, dict] = {}

    def _load_versions():
        """Load versions from existing drawers."""
        try:
            all_data = collection.get(include=["metadatas"], limit=10000)
            for drawer_id, meta in zip(all_data["ids"], all_data["metadatas"]):
                _versions[drawer_id] = int(meta.get("version", 1))
                _metadata[drawer_id] = meta
        except Exception:
            pass

    _load_versions()

    def _wal_log(operation: str, user_id: str, params: dict, from_ip: str = ""):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "user_id": user_id,
            "params": params,
            "from_ip": from_ip,
        }
        try:
            with open(wal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"WAL write failed: {e}")

    def _get_config():
        """Reload config each request to pick up user changes."""
        return TeamServerConfig(config_path=config_path)

    def _auth(api_key: str) -> dict | None:
        cfg = _get_config()
        return resolve_user(api_key, cfg.users)

    # ── Health (no auth) ──

    @app.get("/api/v1/health")
    def health():
        return {"ok": True}

    # ── Auth middleware helper ──

    def _require_auth(x_api_key: str):
        if not x_api_key:
            return None, JSONResponse(status_code=401, content={"error": "Missing X-API-Key"})
        user = _auth(x_api_key)
        if user is None:
            return None, JSONResponse(status_code=401, content={"error": "Invalid API key"})
        return user, None

    # ── Status ──

    @app.get("/api/v1/status")
    def status(x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        return {
            "version": __version__,
            "total_drawers": collection.count(),
            "user": user["user_id"],
        }

    # ── Drawers ──

    @app.post("/api/v1/drawers", status_code=201)
    def add_drawer(request: Request, body: dict, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        wing = body.get("wing", "")
        room = body.get("room", "")
        content = body.get("content", "")
        source_type = body.get("source_type", "direct")
        origin = body.get("origin")

        try:
            wing = sanitize_name(wing, "wing")
            room = sanitize_name(room, "room")
            content = sanitize_content(content)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

        if not check_wing_permission(user, wing, "write"):
            return JSONResponse(status_code=403, content={"error": f"No write access to {wing}"})

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:24]
        drawer_id = f"team_{content_hash}"

        now = datetime.now().isoformat()
        meta = {
            "wing": wing,
            "room": room,
            "published_by": user["user_id"],
            "published_at": now,
            "source_type": source_type,
            "version": 1,
        }
        if origin:
            meta["origin_local_id"] = origin.get("local_id", "")
            meta["origin_user_id"] = origin.get("user_id", "")

        collection.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
        _versions[drawer_id] = 1
        _metadata[drawer_id] = meta

        _wal_log("add_drawer", user["user_id"], {
            "drawer_id": drawer_id, "wing": wing, "room": room,
        }, from_ip=request.client.host if request.client else "")

        return {"drawer_id": drawer_id, "version": 1}

    @app.patch("/api/v1/drawers/{drawer_id}")
    def update_drawer(
        drawer_id: str, request: Request, body: dict,
        x_api_key: str = Header(None), if_match: str = Header(None),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        current_version = _versions.get(drawer_id)
        if current_version is None:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        if if_match is None or int(if_match) != current_version:
            return JSONResponse(status_code=409, content={
                "error": "Version conflict",
                "current_version": current_version,
            })

        meta = _metadata.get(drawer_id, {})
        wing = meta.get("wing", "")
        if not check_wing_permission(user, wing, "write"):
            return JSONResponse(status_code=403, content={"error": f"No write access to {wing}"})

        new_version = current_version + 1
        content = body.get("content")
        if content:
            content = sanitize_content(content)

        # Update metadata
        meta["version"] = new_version
        meta["published_at"] = datetime.now().isoformat()
        if content:
            collection.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
        else:
            collection.upsert(ids=[drawer_id], metadatas=[meta])

        _versions[drawer_id] = new_version
        _metadata[drawer_id] = meta

        _wal_log("update_drawer", user["user_id"], {
            "drawer_id": drawer_id, "new_version": new_version,
        }, from_ip=request.client.host if request.client else "")

        return {"drawer_id": drawer_id, "version": new_version}

    @app.delete("/api/v1/drawers/{drawer_id}")
    def delete_drawer(
        drawer_id: str, request: Request,
        x_api_key: str = Header(None), if_match: str = Header(None),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        current_version = _versions.get(drawer_id)
        if current_version is None:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        if if_match is None or int(if_match) != current_version:
            return JSONResponse(status_code=409, content={
                "error": "Version conflict",
                "current_version": current_version,
            })

        meta = _metadata.get(drawer_id, {})
        # Admin can delete any; member can only delete own
        if user["role"] != "admin" and meta.get("published_by") != user["user_id"]:
            return JSONResponse(status_code=403, content={"error": "Can only delete own drawers"})

        collection.delete(ids=[drawer_id])
        del _versions[drawer_id]
        del _metadata[drawer_id]

        _wal_log("delete_drawer", user["user_id"], {
            "drawer_id": drawer_id,
        }, from_ip=request.client.host if request.client else "")

        return {"success": True, "drawer_id": drawer_id}

    # ── Search ──

    @app.post("/api/v1/search")
    def search_drawers(body: dict, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        query = body.get("query", "")
        n_results = body.get("n_results", 5)
        wing = body.get("wing")
        room = body.get("room")

        where = {}
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}

        try:
            kwargs = {
                "query_texts": [query],
                "n_results": n_results,
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where
            results = collection.query(**kwargs)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        hits = []
        if results["ids"] and results["ids"][0]:
            for doc, meta, dist, did in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                results["ids"][0],
            ):
                hit_wing = meta.get("wing", "")
                if not check_wing_permission(user, hit_wing, "read"):
                    continue
                hits.append({
                    "id": did,
                    "content": doc,
                    "wing": hit_wing,
                    "room": meta.get("room", ""),
                    "similarity": round(1 - dist, 3),
                    "version": int(meta.get("version", 1)),
                    "published_by": meta.get("published_by", ""),
                    "origin_local_id": meta.get("origin_local_id", ""),
                })

        return {"query": query, "results": hits}

    # ── List / Get drawers ──

    @app.get("/api/v1/drawers")
    def list_drawers(
        x_api_key: str = Header(None),
        wing: str = Query(None),
        room: str = Query(None),
        published_by: str = Query(None),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        where_clauses = []
        if wing:
            where_clauses.append({"wing": wing})
        if room:
            where_clauses.append({"room": room})
        if published_by:
            where_clauses.append({"published_by": published_by})

        where = {}
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        try:
            kwargs = {"include": ["metadatas", "documents"], "limit": 10000}
            if where:
                kwargs["where"] = where
            results = collection.get(**kwargs)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        drawers = []
        for did, meta, doc in zip(results["ids"], results["metadatas"], results["documents"]):
            d_wing = meta.get("wing", "")
            if not check_wing_permission(user, d_wing, "read"):
                continue
            drawers.append({
                "id": did,
                "wing": d_wing,
                "room": meta.get("room", ""),
                "published_by": meta.get("published_by", ""),
                "published_at": meta.get("published_at", ""),
                "version": int(meta.get("version", 1)),
                "content_preview": doc[:200] if doc else "",
            })

        return {"drawers": drawers}

    @app.get("/api/v1/drawers/{drawer_id}")
    def get_drawer(drawer_id: str, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        try:
            result = collection.get(ids=[drawer_id], include=["documents", "metadatas"])
        except Exception:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        if not result["ids"]:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        meta = result["metadatas"][0]
        d_wing = meta.get("wing", "")
        if not check_wing_permission(user, d_wing, "read"):
            return JSONResponse(status_code=403, content={"error": f"No read access to {d_wing}"})

        return {
            "id": drawer_id,
            "content": result["documents"][0],
            "wing": d_wing,
            "room": meta.get("room", ""),
            "published_by": meta.get("published_by", ""),
            "published_at": meta.get("published_at", ""),
            "source_type": meta.get("source_type", ""),
            "version": int(meta.get("version", 1)),
            "origin_local_id": meta.get("origin_local_id", ""),
            "origin_user_id": meta.get("origin_user_id", ""),
        }

    # ── Wings / Taxonomy ──

    @app.get("/api/v1/wings")
    def list_wings(x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        wings = {}
        try:
            all_meta = collection.get(include=["metadatas"], limit=10000)["metadatas"]
            for m in all_meta:
                w = m.get("wing", "unknown")
                if check_wing_permission(user, w, "read"):
                    wings[w] = wings.get(w, 0) + 1
        except Exception:
            pass
        return {"wings": wings}

    @app.get("/api/v1/wings/{wing}/rooms")
    def list_rooms(wing: str, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        if not check_wing_permission(user, wing, "read"):
            return JSONResponse(status_code=403, content={"error": f"No read access to {wing}"})
        rooms = {}
        try:
            results = collection.get(where={"wing": wing}, include=["metadatas"], limit=10000)
            for m in results["metadatas"]:
                r = m.get("room", "unknown")
                rooms[r] = rooms.get(r, 0) + 1
        except Exception:
            pass
        return {"wing": wing, "rooms": rooms}

    @app.get("/api/v1/taxonomy")
    def taxonomy(x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        tax = {}
        try:
            all_meta = collection.get(include=["metadatas"], limit=10000)["metadatas"]
            for m in all_meta:
                w = m.get("wing", "unknown")
                if not check_wing_permission(user, w, "read"):
                    continue
                r = m.get("room", "unknown")
                if w not in tax:
                    tax[w] = {}
                tax[w][r] = tax[w].get(r, 0) + 1
        except Exception:
            pass
        return {"taxonomy": tax}

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && pip install fastapi httpx uvicorn && python -m pytest tests/test_team_server.py -v`
Expected: All passed

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass (new + existing)

- [ ] **Step 6: Commit**

```bash
git add cortex/team_server.py tests/test_team_server.py
git commit -m "feat(team): add team server — auth, CRUD, search, versioning endpoints"
```

---

## Task 5: Team Server — Knowledge Graph Endpoints

**Files:**
- Modify: `cortex/team_server.py`
- Modify: `tests/test_team_server.py`

- [ ] **Step 1: Write failing tests for KG endpoints**

Add to `tests/test_team_server.py`:

```python
def test_kg_add_and_query(team_env):
    """Add a KG triple and query it back."""
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/kg/add", headers=headers, json={
        "subject": "Maya",
        "predicate": "completed",
        "object": "auth migration",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = team_env["client"].post("/api/v1/kg/query", headers=headers, json={
        "entity": "Maya",
    })
    assert resp.status_code == 200
    facts = resp.json()["facts"]
    assert len(facts) >= 1
    assert any(f["predicate"] == "completed" for f in facts)


def test_kg_invalidate(team_env):
    """Invalidate a triple."""
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/kg/add", headers=headers, json={
        "subject": "Max", "predicate": "does", "object": "swimming",
    })
    resp = team_env["client"].post("/api/v1/kg/invalidate", headers=headers, json={
        "subject": "Max", "predicate": "does", "object": "swimming",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_kg_timeline(team_env):
    """Get entity timeline."""
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/kg/add", headers=headers, json={
        "subject": "project", "predicate": "started", "object": "v2",
    })
    resp = team_env["client"].get("/api/v1/kg/timeline/project", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["timeline"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_server.py::test_kg_add_and_query -v`
Expected: FAIL — 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Add KG endpoints to team_server.py**

Add inside `create_app()`, after the taxonomy endpoint, before `return app`:

```python
    # ── Knowledge Graph ──

    from .knowledge_graph import KnowledgeGraph

    kg_path = str(data_path / "knowledge_graph.sqlite3")
    team_kg = KnowledgeGraph(db_path=kg_path)

    @app.post("/api/v1/kg/query")
    def kg_query(body: dict, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        entity = body.get("entity", "")
        as_of = body.get("as_of")
        direction = body.get("direction", "both")
        results = team_kg.query_entity(entity, as_of=as_of, direction=direction)
        return {"entity": entity, "facts": results, "count": len(results)}

    @app.post("/api/v1/kg/add")
    def kg_add(body: dict, request: Request, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        subject = body.get("subject", "")
        predicate = body.get("predicate", "")
        obj = body.get("object", "")
        valid_from = body.get("valid_from")
        source_closet = body.get("source_closet")
        try:
            subject = sanitize_name(subject, "subject")
            predicate = sanitize_name(predicate, "predicate")
            obj = sanitize_name(obj, "object")
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        _wal_log("kg_add", user["user_id"], {
            "subject": subject, "predicate": predicate, "object": obj,
        }, from_ip=request.client.host if request.client else "")
        triple_id = team_kg.add_triple(subject, predicate, obj, valid_from=valid_from, source_closet=source_closet)
        return {"success": True, "triple_id": triple_id}

    @app.post("/api/v1/kg/invalidate")
    def kg_invalidate(body: dict, request: Request, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        subject = body.get("subject", "")
        predicate = body.get("predicate", "")
        obj = body.get("object", "")
        ended = body.get("ended")
        _wal_log("kg_invalidate", user["user_id"], {
            "subject": subject, "predicate": predicate, "object": obj,
        }, from_ip=request.client.host if request.client else "")
        team_kg.invalidate(subject, predicate, obj, ended=ended)
        return {"success": True}

    @app.get("/api/v1/kg/timeline/{entity}")
    def kg_timeline(entity: str, x_api_key: str = Header(None)):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        results = team_kg.timeline(entity)
        return {"entity": entity, "timeline": results, "count": len(results)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_server.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add cortex/team_server.py tests/test_team_server.py
git commit -m "feat(team): add knowledge graph endpoints to team server"
```

---

## Task 6: TeamClient — HTTP Client

**Files:**
- Create: `cortex/team_client.py`
- Create: `tests/test_team_client.py`

- [ ] **Step 1: Write failing tests for team client**

```python
# tests/test_team_client.py
"""Tests for TeamClient — HTTP client for team server."""
import json
import pytest

pytest.importorskip("httpx")

from unittest.mock import AsyncMock, patch
from cortex.team_client import TeamClient


@pytest.fixture
def client():
    return TeamClient(
        server_url="https://team.example.com",
        api_key="ak_testkey",
        timeout=3,
    )


def test_client_init(client):
    """Client stores config correctly."""
    assert client.server_url == "https://team.example.com"
    assert client.timeout == 3


def test_client_rejects_http():
    """Non-localhost HTTP is rejected."""
    with pytest.raises(ValueError, match="HTTPS required"):
        TeamClient(server_url="http://team.example.com", api_key="ak_test", timeout=3)


def test_client_allows_localhost_http():
    """Localhost HTTP is allowed for development."""
    client = TeamClient(server_url="http://localhost:8900", api_key="ak_test", timeout=3)
    assert client.server_url == "http://localhost:8900"


def test_client_allows_127_http():
    """127.0.0.1 HTTP is allowed for development."""
    client = TeamClient(server_url="http://127.0.0.1:8900", api_key="ak_test", timeout=3)
    assert client.server_url == "http://127.0.0.1:8900"


@pytest.mark.asyncio
async def test_search(client):
    """Search sends correct request."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "query": "test",
        "results": [{"id": "team_abc", "content": "result", "similarity": 0.9}],
    }

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        result = await client.search("test query", n_results=5)
        mock_post.assert_called_once_with("/api/v1/search", {
            "query": "test query", "n_results": 5, "wing": None, "room": None,
        })
        assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_add_drawer(client):
    """Add drawer sends correct request."""
    mock_response = AsyncMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"drawer_id": "team_abc", "version": 1}

    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        result = await client.add_drawer(
            wing="wing_test", room="room_a", content="test content",
            source_type="publish", origin={"local_id": "local_abc", "user_id": "andy"},
        )
        assert result["drawer_id"] == "team_abc"


@pytest.mark.asyncio
async def test_timeout_returns_unavailable(client):
    """Timeout returns unavailable status, not exception."""
    import httpx

    with patch.object(client, "_post", side_effect=httpx.TimeoutException("timeout")):
        result = await client.search("test", n_results=5)
        assert result["team"] == "timeout"


@pytest.mark.asyncio
async def test_connection_error_returns_unavailable(client):
    """Connection error returns unavailable status."""
    import httpx

    with patch.object(client, "_post", side_effect=httpx.ConnectError("refused")):
        result = await client.search("test", n_results=5)
        assert result["team"] == "unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement team_client.py**

```python
# cortex/team_client.py
"""Async HTTP client for the team memory server."""

import logging
from urllib.parse import urlparse

logger = logging.getLogger("cortex_team_client")


class TeamClient:
    """HTTP client for team server. Handles auth, timeouts, error wrapping."""

    def __init__(self, server_url: str, api_key: str, timeout: int):
        parsed = urlparse(server_url)
        is_local = parsed.hostname in ("localhost", "127.0.0.1")
        if parsed.scheme != "https" and not is_local:
            raise ValueError(f"HTTPS required for non-localhost servers (got {server_url})")
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.server_url,
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout,
            )
        return self._client

    async def _post(self, path: str, body: dict):
        client = self._get_client()
        return await client.post(path, json=body)

    async def _get(self, path: str, params: dict = None):
        client = self._get_client()
        return await client.get(path, params=params)

    async def _patch(self, path: str, body: dict, version: int):
        client = self._get_client()
        return await client.patch(path, json=body, headers={"If-Match": str(version)})

    async def _delete(self, path: str, version: int):
        client = self._get_client()
        return await client.delete(path, headers={"If-Match": str(version)})

    async def _safe_request(self, coro):
        """Wrap request to catch timeout/connection errors."""
        import httpx
        try:
            return await coro
        except httpx.TimeoutException:
            return _error_result("timeout")
        except httpx.ConnectError:
            return _error_result("unavailable")
        except Exception as e:
            logger.error(f"Team server error: {e}")
            return _error_result("unavailable")

    async def search(self, query: str, n_results: int = 5, wing: str = None, room: str = None):
        result = await self._safe_request(
            self._post("/api/v1/search", {
                "query": query, "n_results": n_results, "wing": wing, "room": room,
            })
        )
        if isinstance(result, dict):
            return result  # error result
        return result.json()

    async def add_drawer(self, wing: str, room: str, content: str,
                         source_type: str = "direct", origin: dict = None):
        body = {"wing": wing, "room": room, "content": content, "source_type": source_type}
        if origin:
            body["origin"] = origin
        result = await self._safe_request(self._post("/api/v1/drawers", body))
        if isinstance(result, dict):
            return result
        return result.json()

    async def update_drawer(self, drawer_id: str, content: str, version: int):
        result = await self._safe_request(
            self._patch(f"/api/v1/drawers/{drawer_id}", {"content": content}, version)
        )
        if isinstance(result, dict):
            return result
        if result.status_code == 409:
            return {"error": "conflict", "current_version": result.json().get("current_version")}
        return result.json()

    async def get_drawer(self, drawer_id: str):
        result = await self._safe_request(self._get(f"/api/v1/drawers/{drawer_id}"))
        if isinstance(result, dict):
            return result
        return result.json()

    async def status(self):
        result = await self._safe_request(self._get("/api/v1/status"))
        if isinstance(result, dict):
            return result
        return result.json()

    async def list_wings(self):
        result = await self._safe_request(self._get("/api/v1/wings"))
        if isinstance(result, dict):
            return result
        return result.json()

    async def list_rooms(self, wing: str):
        result = await self._safe_request(self._get(f"/api/v1/wings/{wing}/rooms"))
        if isinstance(result, dict):
            return result
        return result.json()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def _error_result(status: str) -> dict:
    """Return a standardized error dict for failed team requests."""
    return {"team": status, "results": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && pip install pytest-asyncio && python -m pytest tests/test_team_client.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add cortex/team_client.py tests/test_team_client.py
git commit -m "feat(team): add async HTTP client with timeout/error handling"
```

---

## Task 7: Team Router — RRF Merge and Routing

**Files:**
- Create: `cortex/team_router.py`
- Create: `tests/test_team_router.py`

- [ ] **Step 1: Write failing tests for RRF merge and routing**

```python
# tests/test_team_router.py
"""Tests for team router: RRF merge, dedupe, routing decisions."""
import pytest
from cortex.team_router import rrf_merge, dedupe, determine_layer


def test_rrf_merge_basic():
    """RRF merge ranks by position, not score."""
    local_hits = [
        {"id": "a", "similarity": 0.95},
        {"id": "b", "similarity": 0.80},
    ]
    team_hits = [
        {"id": "b", "similarity": 0.70},
        {"id": "c", "similarity": 0.65},
    ]
    merged = rrf_merge(local_hits, team_hits, k=60)
    ids = [h["id"] for h in merged]
    # b appears in both, should rank highest
    assert ids[0] == "b"


def test_rrf_merge_empty_team():
    """If team is empty, local results come through."""
    local_hits = [
        {"id": "a", "similarity": 0.9},
        {"id": "b", "similarity": 0.8},
    ]
    merged = rrf_merge(local_hits, [], k=60)
    assert len(merged) == 2
    assert merged[0]["id"] == "a"


def test_rrf_merge_empty_both():
    """Both empty returns empty."""
    assert rrf_merge([], [], k=60) == []


def test_dedupe_by_origin():
    """Dedupe uses origin link first."""
    local_hits = [
        {"id": "local_abc", "content_hash": "abc", "similarity": 0.9},
    ]
    team_hits = [
        {"id": "team_xyz", "origin_local_id": "local_abc", "content_hash": "different", "similarity": 0.7},
    ]
    deduped_local, deduped_team = dedupe(local_hits, team_hits)
    # Both should be present but linked — team hit removed from separate list
    total_ids = [h["id"] for h in deduped_local] + [h["id"] for h in deduped_team]
    # The team hit that matches local by origin should be merged, not duplicated
    assert len(deduped_local) + len(deduped_team) <= 2


def test_dedupe_by_content_hash():
    """Dedupe falls back to content_hash."""
    local_hits = [
        {"id": "local_abc", "content_hash": "same_hash", "similarity": 0.9},
    ]
    team_hits = [
        {"id": "team_def", "origin_local_id": "", "content_hash": "same_hash", "similarity": 0.7},
    ]
    deduped_local, deduped_team = dedupe(local_hits, team_hits)
    total_ids = [h["id"] for h in deduped_local] + [h["id"] for h in deduped_team]
    assert len(deduped_local) + len(deduped_team) <= 2


def test_determine_layer():
    """Layer determination from hit metadata."""
    assert determine_layer({"id": "local_abc"}) == "local"
    assert determine_layer({"id": "team_abc"}) == "team"
    assert determine_layer({"id": "local_abc", "_matched_team": True}) == "both"
    # Legacy no-prefix = local
    assert determine_layer({"id": "drawer_wing_room_hash"}) == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_router.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement team_router.py**

```python
# cortex/team_router.py
"""Routing layer: decides local/team/both, RRF merge, dedupe."""


def rrf_merge(local_hits: list, team_hits: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion merge.

    Scores each hit by 1/(k+rank) per layer, sums across layers.
    Hits appearing in both layers get boosted naturally.
    """
    scores = {}
    hit_data = {}

    for rank, hit in enumerate(local_hits):
        hid = hit["id"]
        scores[hid] = scores.get(hid, 0) + 1 / (k + rank)
        if hid not in hit_data:
            hit_data[hid] = {**hit, "layer": "local"}

    for rank, hit in enumerate(team_hits):
        hid = hit["id"]
        scores[hid] = scores.get(hid, 0) + 1 / (k + rank)
        if hid in hit_data:
            hit_data[hid]["_matched_team"] = True
        else:
            hit_data[hid] = {**hit, "layer": "team"}

    result = []
    for hid in sorted(scores, key=scores.get, reverse=True):
        entry = hit_data[hid]
        entry["rrf_score"] = scores[hid]
        entry["layer"] = determine_layer(entry)
        result.append(entry)

    return result


def dedupe(local_hits: list, team_hits: list) -> tuple[list, list]:
    """Deduplicate across layers.

    First pass: match by origin link (team drawer's origin_local_id == local id).
    Second pass: match by content_hash.
    Returns (deduped_local, deduped_team) with matched pairs kept in both
    but marked so RRF can boost them.
    """
    # Build lookup from local IDs
    local_by_id = {h["id"]: h for h in local_hits}
    local_by_hash = {}
    for h in local_hits:
        ch = h.get("content_hash", "")
        if ch:
            local_by_hash[ch] = h

    deduped_team = []
    matched_local_ids = set()

    for th in team_hits:
        origin_id = th.get("origin_local_id", "")
        content_hash = th.get("content_hash", "")

        matched_local = None
        # Pass 1: origin link
        if origin_id and origin_id in local_by_id:
            matched_local = local_by_id[origin_id]
        # Pass 2: content hash
        elif content_hash and content_hash in local_by_hash:
            matched_local = local_by_hash[content_hash]

        if matched_local:
            # Mark both as matched — they'll appear in both rank lists for RRF boost
            matched_local["_matched_team"] = True
            matched_local_ids.add(matched_local["id"])
            # Use the team hit's ID in team list for RRF ranking, but link them
            team_entry = {**th, "id": matched_local["id"]}  # use same ID so RRF merges them
            deduped_team.append(team_entry)
        else:
            deduped_team.append(th)

    return local_hits, deduped_team


def determine_layer(hit: dict) -> str:
    """Determine which layer(s) a hit belongs to."""
    if hit.get("_matched_team"):
        return "both"
    hid = hit.get("id", "")
    if hid.startswith("team_"):
        return "team"
    return "local"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_router.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add cortex/team_router.py tests/test_team_router.py
git commit -m "feat(team): add router with RRF merge and origin-based dedupe"
```

---

## Task 8: Wire Router into MCP Server

**Files:**
- Modify: `cortex/mcp_server.py`
- Create: `tests/test_mcp_team_routing.py`

- [ ] **Step 1: Write failing tests for MCP team routing**

```python
# tests/test_mcp_team_routing.py
"""Tests for team routing wired into MCP server."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from cortex.mcp_server import tool_search, tool_status, tool_list_wings


def test_search_without_team_config(tmp_path, monkeypatch):
    """Search without team config returns local-only results."""
    # This should work exactly as before — no team routing
    # The test verifies the tool still works when team is not configured
    import cortex.mcp_server as mcp
    mock_config = MagicMock()
    mock_config.team_enabled = False
    mock_config.palace_path = str(tmp_path / "palace")
    monkeypatch.setattr(mcp, "_config", mock_config)
    # With no palace, we get the no_palace error — that's fine,
    # we're testing that team routing doesn't crash
    result = tool_search("test query")
    assert "error" in result or "results" in result


def test_publish_tool_exists():
    """cortex_publish tool is registered."""
    from cortex.mcp_server import TOOLS
    assert "cortex_publish" in TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_mcp_team_routing.py -v`
Expected: FAIL — `cortex_publish` not in TOOLS

- [ ] **Step 3: Add publish tool and team routing to mcp_server.py**

Add the publish tool registration to the `TOOLS` dict in `mcp_server.py`:

```python
# Add after cortex_delete_drawer in TOOLS dict
"cortex_publish": {
    "description": "Publish a local drawer to the team layer. First publish creates a new team drawer; re-publish updates the existing one. Requires team config.",
    "input_schema": {
        "type": "object",
        "properties": {
            "drawer_id": {"type": "string", "description": "Local drawer ID to publish"},
            "target_wing": {"type": "string", "description": "Override wing on team layer (optional)"},
            "target_room": {"type": "string", "description": "Override room on team layer (optional)"},
        },
        "required": ["drawer_id"],
    },
    "handler": tool_publish,
},
```

Add the handler function before the TOOLS dict:

```python
def tool_publish(drawer_id: str, target_wing: str = None, target_room: str = None):
    """Publish a local drawer to the team server."""
    if not _config.team_enabled:
        return {"success": False, "error": "Team layer not configured"}

    col = _get_collection()
    if not col:
        return _no_palace()

    # Read local drawer
    try:
        result = col.get(ids=[drawer_id], include=["documents", "metadatas"])
    except Exception:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}

    if not result["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}

    content = result["documents"][0]
    meta = result["metadatas"][0]
    wing = target_wing or meta.get("wing", "")
    room = target_room or meta.get("room", "")

    # Check if this is a re-publish
    published_as = meta.get("published_as_team_id", "")

    import asyncio
    from .team_client import TeamClient

    client = TeamClient(
        server_url=_config.team_server,
        api_key=_config.team_api_key,
        timeout=_config.team_timeout,
    )

    try:
        if published_as:
            # Re-publish: PATCH existing team drawer
            version = int(meta.get("published_as_version", 1))
            result = asyncio.get_event_loop().run_until_complete(
                client.update_drawer(published_as, content, version)
            )
            if "error" in result and result["error"] == "conflict":
                return {"success": False, "error": "Version conflict on team server", **result}
            # Update local metadata with new version
            new_version = result.get("version", version + 1)
            meta["published_as_team_id"] = published_as
            meta["published_as_version"] = new_version
            meta["published_as_at"] = result.get("published_at", "")
            col.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
            return {"success": True, "team_drawer_id": published_as, "version": new_version, "action": "updated"}
        else:
            # First publish
            result = asyncio.get_event_loop().run_until_complete(
                client.add_drawer(
                    wing=wing, room=room, content=content,
                    source_type="publish",
                    origin={"local_id": drawer_id, "user_id": "local"},
                )
            )
            if "team" in result:
                return {"success": False, "error": f"Team server {result['team']}"}
            team_id = result.get("drawer_id", "")
            version = result.get("version", 1)
            # Store published_as on local drawer
            meta["published_as_team_id"] = team_id
            meta["published_as_version"] = version
            from datetime import datetime
            meta["published_as_at"] = datetime.now().isoformat()
            col.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
            return {"success": True, "team_drawer_id": team_id, "version": version, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        asyncio.get_event_loop().run_until_complete(client.close())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_mcp_team_routing.py -v`
Expected: All passed

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add cortex/mcp_server.py tests/test_mcp_team_routing.py
git commit -m "feat(team): wire publish tool and team routing into MCP server"
```

---

## Task 9: CLI — Team Subcommands

**Files:**
- Create: `cortex/team_cli.py`
- Modify: `cortex/cli.py`
- Create: `tests/test_team_cli.py`

- [ ] **Step 1: Write failing tests for team CLI**

```python
# tests/test_team_cli.py
"""Tests for team CLI subcommands."""
import json
import pytest
from unittest.mock import patch, MagicMock
from cortex.team_cli import cmd_team_init, cmd_team_status, cmd_team_whoami, cmd_team_add_user, cmd_team_remove_user


def test_team_init_creates_config(tmp_path, monkeypatch):
    """team init writes team config to config.json."""
    config_dir = tmp_path / ".cortex"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"palace_path": str(tmp_path / "palace")}))

    mock_args = MagicMock()
    mock_args.server = "https://team.example.com"
    mock_args.api_key = "ak_test123"

    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("cortex.team_cli.CortexConfig") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg._config_dir = config_dir
        mock_cfg._config_file = config_dir / "config.json"
        mock_cfg._file_config = json.loads((config_dir / "config.json").read_text())
        MockConfig.return_value = mock_cfg
        cmd_team_init(mock_args)

    saved = json.loads((config_dir / "config.json").read_text())
    assert saved["team"]["enabled"] is True
    assert saved["team"]["server"] == "https://team.example.com"


def test_team_add_user(tmp_path, capsys):
    """team add-user generates and prints API key."""
    config_path = tmp_path / "team_config.json"
    mock_args = MagicMock()
    mock_args.id = "kai"
    mock_args.role = "member"
    mock_args.read_wings = "frontend,shared"
    mock_args.write_wings = "frontend"

    with patch("cortex.team_cli._get_team_config_path", return_value=str(config_path)):
        cmd_team_add_user(mock_args)

    captured = capsys.readouterr()
    assert "ak_" in captured.out
    # Config file should exist with the user
    saved = json.loads(config_path.read_text())
    assert any(u["user_id"] == "kai" for u in saved["users"].values())


def test_team_remove_user(tmp_path, capsys):
    """team remove-user removes the user."""
    config_path = tmp_path / "team_config.json"
    # Pre-create with a user
    from cortex.team_config import TeamServerConfig
    cfg = TeamServerConfig(config_path=str(config_path))
    cfg.add_user("kai", "member", ["frontend"], ["frontend"])

    mock_args = MagicMock()
    mock_args.id = "kai"

    with patch("cortex.team_cli._get_team_config_path", return_value=str(config_path)):
        cmd_team_remove_user(mock_args)

    saved = json.loads(config_path.read_text())
    assert not any(u["user_id"] == "kai" for u in saved["users"].values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement team_cli.py**

```python
# cortex/team_cli.py
"""CLI subcommands for team management."""

import json
import os

from .config import CortexConfig
from .team_config import TeamServerConfig


def _get_team_config_path():
    """Default path for team server config."""
    return os.path.expanduser("/var/cortex-team/team_config.json")


def cmd_team_init(args):
    """Interactive setup: write team config to config.json."""
    cfg = CortexConfig()
    config = cfg._file_config.copy()
    config["team"] = {
        "enabled": True,
        "server": args.server,
        "api_key": args.api_key,
        "timeout_seconds": getattr(args, "timeout", 3),
    }
    with open(cfg._config_file, "w") as f:
        json.dump(config, f, indent=2)
    try:
        cfg._config_file.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    print(f"  Team configured: {args.server}")


def cmd_team_status(args):
    """Show team connection status."""
    cfg = CortexConfig()
    if not cfg.team_enabled:
        print("  Team layer: not configured")
        return
    print(f"  Server: {cfg.team_server}")
    print(f"  Timeout: {cfg.team_timeout}s")
    # Try to connect
    import asyncio
    from .team_client import TeamClient
    client = TeamClient(
        server_url=cfg.team_server,
        api_key=cfg.team_api_key,
        timeout=cfg.team_timeout,
    )
    result = asyncio.get_event_loop().run_until_complete(client.status())
    asyncio.get_event_loop().run_until_complete(client.close())
    if "team" in result:
        print(f"  Status: {result['team']}")
    else:
        print(f"  Status: connected")
        print(f"  Server version: {result.get('version', '?')}")
        print(f"  Total drawers: {result.get('total_drawers', '?')}")


def cmd_team_whoami(args):
    """Show current user and accessible wings."""
    cfg = CortexConfig()
    if not cfg.team_enabled:
        print("  Team layer: not configured")
        return
    import asyncio
    from .team_client import TeamClient
    client = TeamClient(
        server_url=cfg.team_server,
        api_key=cfg.team_api_key,
        timeout=cfg.team_timeout,
    )
    result = asyncio.get_event_loop().run_until_complete(client.status())
    asyncio.get_event_loop().run_until_complete(client.close())
    if "team" in result:
        print(f"  Status: {result['team']}")
    else:
        print(f"  User: {result.get('user', '?')}")


def cmd_team_serve(args):
    """Start the team server."""
    import uvicorn
    from .team_server import create_app

    config_path = getattr(args, "config", _get_team_config_path())
    data_dir = getattr(args, "data_dir", "/var/cortex-team/data")
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8900)

    app = create_app(config_path=config_path, data_dir=data_dir)
    print(f"  Cortex Team Server starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def cmd_team_add_user(args):
    """Add a new user to the team server."""
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    read_wings = [w.strip() for w in args.read_wings.split(",")]
    write_wings = [w.strip() for w in args.write_wings.split(",")]
    api_key = cfg.add_user(
        user_id=args.id,
        role=args.role,
        read_wings=read_wings,
        write_wings=write_wings,
    )
    print(f"  User '{args.id}' added ({args.role})")
    print(f"  API Key: {api_key}")
    print(f"  (shown once — save it now)")


def cmd_team_remove_user(args):
    """Remove a user from the team server."""
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    cfg.remove_user(args.id)
    print(f"  User '{args.id}' removed")


def cmd_team_rotate_key(args):
    """Rotate API key for a user."""
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    new_key = cfg.rotate_key(args.id)
    print(f"  New key for '{args.id}': {new_key}")
    print(f"  Old key valid for 24 hours")


def add_team_subparser(subparsers):
    """Register team subcommands on the CLI parser."""
    team_parser = subparsers.add_parser("team", help="Team server management")
    team_sub = team_parser.add_subparsers(dest="team_command")

    # team init
    p = team_sub.add_parser("init", help="Configure team server connection")
    p.add_argument("--server", required=True, help="Team server URL")
    p.add_argument("--api-key", required=True, dest="api_key", help="Your API key")

    # team status
    team_sub.add_parser("status", help="Show connection status")

    # team whoami
    team_sub.add_parser("whoami", help="Show current user + wings")

    # team serve
    p = team_sub.add_parser("serve", help="Start team server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8900)
    p.add_argument("--config", default=None)
    p.add_argument("--data-dir", default=None, dest="data_dir")

    # team add-user
    p = team_sub.add_parser("add-user", help="Add a user")
    p.add_argument("--id", required=True)
    p.add_argument("--role", default="member")
    p.add_argument("--read-wings", required=True, dest="read_wings")
    p.add_argument("--write-wings", required=True, dest="write_wings")

    # team remove-user
    p = team_sub.add_parser("remove-user", help="Remove a user")
    p.add_argument("--id", required=True)

    # team rotate-key
    p = team_sub.add_parser("rotate-key", help="Rotate user's API key")
    p.add_argument("--id", required=True)


TEAM_COMMANDS = {
    "init": cmd_team_init,
    "status": cmd_team_status,
    "whoami": cmd_team_whoami,
    "serve": cmd_team_serve,
    "add-user": cmd_team_add_user,
    "remove-user": cmd_team_remove_user,
    "rotate-key": cmd_team_rotate_key,
}
```

- [ ] **Step 4: Wire team commands into cli.py main()**

Add to `cli.py` in the command dispatch section:

```python
# After existing command handling
elif args.command == "team":
    from .team_cli import TEAM_COMMANDS
    handler = TEAM_COMMANDS.get(args.team_command)
    if handler:
        handler(args)
    else:
        print("  Usage: cortex team {init|status|whoami|serve|add-user|remove-user|rotate-key}")
```

And add the subparser in the argument parser setup:

```python
from .team_cli import add_team_subparser
add_team_subparser(subparsers)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_team_cli.py -v`
Expected: All passed

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add cortex/team_cli.py cortex/cli.py tests/test_team_cli.py
git commit -m "feat(team): add team CLI subcommands and wire into main CLI"
```

---

## Task 10: CLI — Publish Command and --layer Flag on Search

**Files:**
- Modify: `cortex/cli.py`
- Create: `tests/test_cli_layer.py`

- [ ] **Step 1: Write failing tests for --layer flag and publish command**

```python
# tests/test_cli_layer.py
"""Tests for --layer flag on search and publish command."""
import pytest
from unittest.mock import patch, MagicMock


def test_search_layer_flag_parsed():
    """--layer flag is accepted by search command."""
    from cortex.cli import main
    import sys
    with patch.object(sys, "argv", ["cortex", "search", "test query", "--layer", "local"]):
        with patch("cortex.cli.cmd_search") as mock_search:
            try:
                main()
            except SystemExit:
                pass
            if mock_search.called:
                args = mock_search.call_args[0][0]
                assert args.layer == "local"


def test_publish_command_parsed():
    """publish command is accepted."""
    from cortex.cli import main
    import sys
    with patch.object(sys, "argv", ["cortex", "publish", "drawer_123"]):
        with patch("cortex.cli.cmd_publish") as mock_publish:
            try:
                main()
            except SystemExit:
                pass
            if mock_publish.called:
                args = mock_publish.call_args[0][0]
                assert args.drawer_id == "drawer_123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_cli_layer.py -v`
Expected: FAIL — no `--layer` argument or `publish` command

- [ ] **Step 3: Add --layer to search and publish command to cli.py**

In the argparse setup for search, add:
```python
search_parser.add_argument("--layer", choices=["local", "team"], default=None, help="Search layer")
```

Add publish subparser:
```python
publish_parser = subparsers.add_parser("publish", help="Publish local drawers to team layer")
publish_parser.add_argument("drawer_id", nargs="?", help="Drawer ID to publish")
publish_parser.add_argument("--wing", help="Override wing for batch publish filter or target")
publish_parser.add_argument("--room", help="Override room for batch publish filter or target")
```

Add `cmd_publish` function:
```python
def cmd_publish(args):
    from .mcp_server import tool_publish
    if args.drawer_id:
        result = tool_publish(
            drawer_id=args.drawer_id,
            target_wing=args.wing,
            target_room=args.room,
        )
        if result.get("success"):
            print(f"  Published: {result['team_drawer_id']} (v{result['version']}, {result['action']})")
        else:
            print(f"  Error: {result.get('error', 'unknown')}")
    else:
        print("  Usage: cortex publish <drawer_id> [--wing W] [--room R]")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_cli_layer.py -v`
Expected: All passed

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add cortex/cli.py tests/test_cli_layer.py
git commit -m "feat(team): add --layer flag on search and publish CLI command"
```

---

## Task 11: Integration Test — Full Publish Flow

**Files:**
- Create: `tests/test_integration_publish.py`

- [ ] **Step 1: Write end-to-end publish test**

```python
# tests/test_integration_publish.py
"""End-to-end test: add local drawer → publish to team → search returns it from team."""
import json
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import chromadb
from fastapi.testclient import TestClient
from cortex.team_auth import hash_api_key
from cortex.team_server import create_app


@pytest.fixture
def full_env(tmp_path):
    """Set up both local palace and team server."""
    # Local palace
    local_palace = tmp_path / "local_palace"
    local_palace.mkdir()
    local_client = chromadb.PersistentClient(path=str(local_palace))
    local_col = local_client.get_or_create_collection("cortex_drawers")

    # Add a local drawer
    local_col.upsert(
        ids=["drawer_wing_test_room_a_abc123"],
        documents=["We chose PostgreSQL because of JSONB support and strong ecosystem."],
        metadatas=[{"wing": "wing_test", "room": "room_decisions", "source_file": "", "chunk_index": 0, "added_by": "test", "filed_at": "2026-04-10T12:00:00"}],
    )

    # Team server
    config_path = tmp_path / "team_config.json"
    data_dir = tmp_path / "team_data"
    data_dir.mkdir()
    api_key = "ak_integration_test_key_000000000"
    key_hash = hash_api_key(api_key)
    config_path.write_text(json.dumps({
        "users": {
            key_hash: {"user_id": "tester", "role": "admin", "wings": {"read": "*", "write": "*"}},
        }
    }))
    app = create_app(config_path=str(config_path), data_dir=str(data_dir))
    team_client = TestClient(app)

    return {
        "local_col": local_col,
        "team_client": team_client,
        "api_key": api_key,
    }


def test_publish_and_search_team(full_env):
    """Publish local drawer to team, then search team for it."""
    headers = {"X-API-Key": full_env["api_key"]}

    # Read local drawer
    local_result = full_env["local_col"].get(
        ids=["drawer_wing_test_room_a_abc123"],
        include=["documents", "metadatas"],
    )
    content = local_result["documents"][0]
    meta = local_result["metadatas"][0]

    # Publish to team
    resp = full_env["team_client"].post("/api/v1/drawers", headers=headers, json={
        "wing": meta["wing"],
        "room": meta["room"],
        "content": content,
        "source_type": "publish",
        "origin": {"local_id": "drawer_wing_test_room_a_abc123", "user_id": "tester"},
    })
    assert resp.status_code == 201
    team_drawer_id = resp.json()["drawer_id"]

    # Search team
    resp = full_env["team_client"].post("/api/v1/search", headers=headers, json={
        "query": "PostgreSQL",
        "n_results": 5,
    })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["id"] == team_drawer_id for r in results)
    assert any("PostgreSQL" in r["content"] for r in results)

    # Verify origin tracking
    resp = full_env["team_client"].get(f"/api/v1/drawers/{team_drawer_id}", headers=headers)
    assert resp.status_code == 200
    drawer = resp.json()
    assert drawer["origin_local_id"] == "drawer_wing_test_room_a_abc123"
    assert drawer["source_type"] == "publish"


def test_re_publish_updates_existing(full_env):
    """Re-publishing updates the team drawer, doesn't create a new one."""
    headers = {"X-API-Key": full_env["api_key"]}

    # First publish
    resp = full_env["team_client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "version 1",
        "source_type": "publish",
        "origin": {"local_id": "local_123", "user_id": "tester"},
    })
    team_id = resp.json()["drawer_id"]
    assert resp.json()["version"] == 1

    # Update (re-publish)
    resp = full_env["team_client"].patch(
        f"/api/v1/drawers/{team_id}",
        headers={**headers, "If-Match": "1"},
        json={"content": "version 2"},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    # Verify content updated
    resp = full_env["team_client"].get(f"/api/v1/drawers/{team_id}", headers=headers)
    assert "version 2" in resp.json()["content"]
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/test_integration_publish.py -v`
Expected: All passed

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/andy/stoneblade/cortex && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_publish.py
git commit -m "test(team): add end-to-end publish flow integration tests"
```

---

## Summary

| Task | Component | Est. Files | Tests |
|------|-----------|-----------|-------|
| 1 | Config extension | 2 modified, 1 new | 3 tests |
| 2 | Auth module | 1 new | 9 tests |
| 3 | Server config | 1 new | 6 tests |
| 4 | Server endpoints | 1 new | 9 tests |
| 5 | Server KG endpoints | 1 modified | 3 tests |
| 6 | HTTP client | 1 new | 7 tests |
| 7 | Router + RRF | 1 new | 6 tests |
| 8 | MCP wiring | 1 modified | 2 tests |
| 9 | Team CLI | 2 modified | 3 tests |
| 10 | Search --layer + publish CLI | 1 modified | 2 tests |
| 11 | Integration test | 1 new | 2 tests |

**Total: 8 new files, 4 modified files, ~50 tests, 11 commits**
