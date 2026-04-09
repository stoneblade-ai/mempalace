"""Tests for team routing wired into MCP server."""
import json
import pytest
from unittest.mock import MagicMock
from mempalace.mcp_server import TOOLS


def test_publish_tool_exists():
    """mempalace_publish tool is registered."""
    assert "mempalace_publish" in TOOLS
    assert "handler" in TOOLS["mempalace_publish"]
    assert "input_schema" in TOOLS["mempalace_publish"]


def test_publish_tool_schema():
    """Publish tool has correct input schema."""
    schema = TOOLS["mempalace_publish"]["input_schema"]
    assert "drawer_id" in schema["properties"]
    assert "target_wing" in schema["properties"]
    assert "target_room" in schema["properties"]
    assert "drawer_id" in schema["required"]


def test_publish_without_team_config():
    """Publish without team config returns error."""
    handler = TOOLS["mempalace_publish"]["handler"]
    # When team is not configured, should return an error
    result = handler("some_drawer_id")
    assert result.get("success") is False
    assert "not configured" in result.get("error", "").lower() or "error" in result
