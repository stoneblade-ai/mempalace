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
            assert mock_search.called, "cmd_search was not dispatched"
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
            assert mock_publish.called, "cmd_publish was not dispatched"
            args = mock_publish.call_args[0][0]
            assert args.drawer_id == "drawer_123"
