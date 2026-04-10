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

    async def _safe_request(self, method, *args, **kwargs):
        """Call an internal request method, catching timeout/connection errors."""
        import httpx
        try:
            result = method(*args, **kwargs)
            # Support both coroutines and plain return values (e.g. mocks in tests)
            if hasattr(result, "__await__"):
                result = await result
            return result
        except httpx.TimeoutException:
            return _error_result("timeout")
        except httpx.ConnectError:
            return _error_result("unavailable")
        except Exception as e:
            logger.error(f"Team server error: {e}")
            return _error_result("unavailable")

    async def _json(self, response):
        """Extract JSON from a response, handling both sync and async .json() methods."""
        data = response.json()
        if hasattr(data, "__await__"):
            data = await data
        import inspect
        if inspect.iscoroutine(data):
            data = await data
        return data

    async def search(self, query: str, n_results: int = 5, wing: str = None, room: str = None):
        result = await self._safe_request(
            self._post, "/api/v1/search", {"query": query, "n_results": n_results, "wing": wing, "room": room}
        )
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def add_drawer(self, wing: str, room: str, content: str,
                         source_type: str = "direct", origin: dict = None):
        body = {"wing": wing, "room": room, "content": content, "source_type": source_type}
        if origin:
            body["origin"] = origin
        result = await self._safe_request(self._post, "/api/v1/drawers", body)
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def update_drawer(self, drawer_id: str, content: str, version: int):
        result = await self._safe_request(
            self._patch, f"/api/v1/drawers/{drawer_id}", {"content": content}, version
        )
        if isinstance(result, dict):
            return result
        if result.status_code == 409:
            return {"error": "conflict", "current_version": (await self._json(result)).get("current_version")}
        return await self._json(result)

    async def get_drawer(self, drawer_id: str):
        result = await self._safe_request(self._get, f"/api/v1/drawers/{drawer_id}")
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def status(self):
        result = await self._safe_request(self._get, "/api/v1/status")
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def list_wings(self):
        result = await self._safe_request(self._get, "/api/v1/wings")
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def list_rooms(self, wing: str):
        result = await self._safe_request(self._get, f"/api/v1/wings/{wing}/rooms")
        if isinstance(result, dict):
            return result
        return await self._json(result)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


def _error_result(status: str) -> dict:
    return {"team": status, "results": []}
