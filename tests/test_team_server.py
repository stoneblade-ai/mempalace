"""Integration tests for team server endpoints."""
import json
import pytest
from mempalace.team_auth import hash_api_key

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from mempalace.team_server import create_app


@pytest.fixture
def team_env(tmp_path):
    config_path = tmp_path / "team_config.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    api_key = "ak_testkey_for_integration_tests00"
    key_hash = hash_api_key(api_key)
    config_path.write_text(json.dumps({
        "users": {
            key_hash: {"user_id": "tester", "role": "admin", "wings": {"read": "*", "write": "*"}},
        }
    }))
    app = create_app(config_path=str(config_path), data_dir=str(data_dir))
    client = TestClient(app)
    return {"client": client, "api_key": api_key, "data_dir": data_dir, "config_path": config_path}


def test_health_no_auth(team_env):
    resp = team_env["client"].get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_status_requires_auth(team_env):
    resp = team_env["client"].get("/api/v1/status")
    assert resp.status_code == 401


def test_status_with_auth(team_env):
    resp = team_env["client"].get("/api/v1/status", headers={"X-API-Key": team_env["api_key"]})
    assert resp.status_code == 200
    assert "version" in resp.json()


def test_add_and_search_drawer(team_env):
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_decisions",
        "content": "We decided to use PostgreSQL for the team knowledge graph at scale.",
        "source_type": "direct",
    })
    assert resp.status_code == 201
    drawer_id = resp.json()["drawer_id"]
    assert drawer_id.startswith("team_")
    assert resp.json()["version"] == 1

    resp = team_env["client"].post("/api/v1/search", headers=headers, json={"query": "PostgreSQL decision", "n_results": 5})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert any("PostgreSQL" in r["content"] for r in results)


def test_update_drawer_with_version(team_env):
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "original", "source_type": "direct",
    })
    drawer_id = resp.json()["drawer_id"]
    resp = team_env["client"].patch(f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "1"}, json={"content": "updated content"})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    resp = team_env["client"].patch(f"/api/v1/drawers/{drawer_id}",
        headers={**headers, "If-Match": "1"}, json={"content": "should fail"})
    assert resp.status_code == 409


def test_delete_drawer_with_version(team_env):
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "to delete", "source_type": "direct",
    })
    drawer_id = resp.json()["drawer_id"]
    resp = team_env["client"].delete(f"/api/v1/drawers/{drawer_id}", headers={**headers, "If-Match": "99"})
    assert resp.status_code == 409
    resp = team_env["client"].delete(f"/api/v1/drawers/{drawer_id}", headers={**headers, "If-Match": "1"})
    assert resp.status_code == 200


def test_permission_denied_wrong_wing(team_env):
    restricted_key = "ak_restricted_user_key_000000000"
    restricted_hash = hash_api_key(restricted_key)
    config = json.loads(team_env["config_path"].read_text())
    config["users"][restricted_hash] = {
        "user_id": "kai", "role": "member",
        "wings": {"read": ["wing_frontend"], "write": ["wing_frontend"]},
    }
    team_env["config_path"].write_text(json.dumps(config))
    resp = team_env["client"].post("/api/v1/drawers",
        headers={"X-API-Key": restricted_key},
        json={"wing": "wing_backend", "room": "room_a", "content": "test", "source_type": "direct"})
    assert resp.status_code == 403


def test_list_drawers(team_env):
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_test", "room": "room_a", "content": "drawer A", "source_type": "direct",
    })
    team_env["client"].post("/api/v1/drawers", headers=headers, json={
        "wing": "wing_other", "room": "room_b", "content": "drawer B", "source_type": "direct",
    })
    resp = team_env["client"].get("/api/v1/drawers", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["drawers"]) >= 2
    resp = team_env["client"].get("/api/v1/drawers?wing=wing_test", headers=headers)
    assert all(d["wing"] == "wing_test" for d in resp.json()["drawers"])


def test_wings_and_taxonomy(team_env):
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


def test_kg_add_and_query(team_env):
    headers = {"X-API-Key": team_env["api_key"]}
    resp = team_env["client"].post("/api/v1/kg/add", headers=headers, json={
        "subject": "Maya", "predicate": "completed", "object": "auth migration",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = team_env["client"].post("/api/v1/kg/query", headers=headers, json={"entity": "Maya"})
    assert resp.status_code == 200
    facts = resp.json()["facts"]
    assert len(facts) >= 1
    assert any(f["predicate"] == "completed" for f in facts)


def test_kg_invalidate(team_env):
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
    headers = {"X-API-Key": team_env["api_key"]}
    team_env["client"].post("/api/v1/kg/add", headers=headers, json={
        "subject": "project", "predicate": "started", "object": "v2",
    })
    resp = team_env["client"].get("/api/v1/kg/timeline/project", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["timeline"]) >= 1
