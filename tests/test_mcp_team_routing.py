"""Tests for team routing wired into MCP server."""
import json
import pytest
from unittest.mock import MagicMock
from cortex.mcp_server import TOOLS


def test_publish_tool_exists():
    """cortex_publish tool is registered."""
    assert "cortex_publish" in TOOLS
    assert "handler" in TOOLS["cortex_publish"]
    assert "input_schema" in TOOLS["cortex_publish"]


def test_publish_tool_schema():
    """Publish tool has correct input schema."""
    schema = TOOLS["cortex_publish"]["input_schema"]
    assert "drawer_id" in schema["properties"]
    assert "target_wing" in schema["properties"]
    assert "target_room" in schema["properties"]
    assert "drawer_id" in schema["required"]


def test_publish_without_team_config():
    """Publish without team config returns error."""
    handler = TOOLS["cortex_publish"]["handler"]
    # When team is not configured, should return an error
    result = handler("some_drawer_id")
    assert result.get("success") is False
    assert "not configured" in result.get("error", "").lower() or "error" in result
