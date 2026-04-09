"""Tests for TeamClient — HTTP client for team server."""
import json
import pytest

pytest.importorskip("httpx")

from unittest.mock import AsyncMock, patch
from mempalace.team_client import TeamClient


@pytest.fixture
def client():
    return TeamClient(server_url="https://team.example.com", api_key="ak_testkey", timeout=3)


def test_client_init(client):
    assert client.server_url == "https://team.example.com"
    assert client.timeout == 3


def test_client_rejects_http():
    with pytest.raises(ValueError, match="HTTPS required"):
        TeamClient(server_url="http://team.example.com", api_key="ak_test", timeout=3)


def test_client_allows_localhost_http():
    c = TeamClient(server_url="http://localhost:8900", api_key="ak_test", timeout=3)
    assert c.server_url == "http://localhost:8900"


def test_client_allows_127_http():
    c = TeamClient(server_url="http://127.0.0.1:8900", api_key="ak_test", timeout=3)
    assert c.server_url == "http://127.0.0.1:8900"


@pytest.mark.asyncio
async def test_search(client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"query": "test", "results": [{"id": "team_abc", "content": "result", "similarity": 0.9}]}
    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        result = await client.search("test query", n_results=5)
        mock_post.assert_called_once_with("/api/v1/search", {"query": "test query", "n_results": 5, "wing": None, "room": None})
        assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_add_drawer(client):
    mock_response = AsyncMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"drawer_id": "team_abc", "version": 1}
    with patch.object(client, "_post", return_value=mock_response) as mock_post:
        result = await client.add_drawer(wing="wing_test", room="room_a", content="test content",
            source_type="publish", origin={"local_id": "local_abc", "user_id": "andy"})
        assert result["drawer_id"] == "team_abc"


@pytest.mark.asyncio
async def test_timeout_returns_unavailable(client):
    import httpx
    with patch.object(client, "_post", side_effect=httpx.TimeoutException("timeout")):
        result = await client.search("test", n_results=5)
        assert result["team"] == "timeout"


@pytest.mark.asyncio
async def test_connection_error_returns_unavailable(client):
    import httpx
    with patch.object(client, "_post", side_effect=httpx.ConnectError("refused")):
        result = await client.search("test", n_results=5)
        assert result["team"] == "unavailable"
