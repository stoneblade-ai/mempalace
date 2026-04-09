# tests/test_integration_publish.py
"""End-to-end test: add local drawer → publish to team → search returns it from team."""
import json
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import chromadb
from fastapi.testclient import TestClient
from mempalace.team_auth import hash_api_key
from mempalace.team_server import create_app


@pytest.fixture
def full_env(tmp_path):
    """Set up both local palace and team server."""
    # Local palace
    local_palace = tmp_path / "local_palace"
    local_palace.mkdir()
    local_client = chromadb.PersistentClient(path=str(local_palace))
    local_col = local_client.get_or_create_collection("mempalace_drawers")

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
    assert any(r["drawer_id"] == team_drawer_id for r in results)
    assert any("PostgreSQL" in r["content"] for r in results)

    # Verify origin tracking
    resp = full_env["team_client"].get(f"/api/v1/drawers/{team_drawer_id}", headers=headers)
    assert resp.status_code == 200
    drawer = resp.json()
    assert drawer["origin_local_id"] == "drawer_wing_test_room_a_abc123"
    assert drawer["source_type"] == "publish"


def test_direct_write_has_no_origin(full_env):
    """Direct writes (not published from local) have empty origin fields."""
    headers = {"X-API-Key": full_env["api_key"]}

    resp = full_env["team_client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test",
        "room": "room_decisions",
        "content": "A direct team note, not published from local.",
        "source_type": "direct",
    })
    assert resp.status_code == 201
    team_drawer_id = resp.json()["drawer_id"]

    resp = full_env["team_client"].get(f"/api/v1/drawers/{team_drawer_id}", headers=headers)
    assert resp.status_code == 200
    drawer = resp.json()
    assert drawer["source_type"] == "direct"
    assert drawer["origin_local_id"] == ""


def test_re_publish_updates_existing(full_env):
    """Re-publishing updates the team drawer, doesn't create a new one."""
    headers = {"X-API-Key": full_env["api_key"]}

    # First publish
    resp = full_env["team_client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "version 1",
        "source_type": "publish",
        "origin": {"local_id": "local_123", "user_id": "tester"},
    })
    assert resp.status_code == 201
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
