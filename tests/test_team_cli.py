"""Tests for team CLI subcommands."""
import json
import pytest
from unittest.mock import patch, MagicMock
from mempalace.team_cli import cmd_team_add_user, cmd_team_remove_user


def test_team_add_user(tmp_path, capsys):
    """team add-user generates and prints API key."""
    config_path = tmp_path / "team_config.json"
    mock_args = MagicMock()
    mock_args.id = "kai"
    mock_args.role = "member"
    mock_args.read_wings = "frontend,shared"
    mock_args.write_wings = "frontend"

    with patch("mempalace.team_cli._get_team_config_path", return_value=str(config_path)):
        cmd_team_add_user(mock_args)

    captured = capsys.readouterr()
    assert "ak_" in captured.out
    saved = json.loads(config_path.read_text())
    assert any(u["user_id"] == "kai" for u in saved["users"].values())


def test_team_remove_user(tmp_path, capsys):
    """team remove-user removes the user."""
    config_path = tmp_path / "team_config.json"
    from mempalace.team_config import TeamServerConfig
    cfg = TeamServerConfig(config_path=str(config_path))
    cfg.add_user("kai", "member", ["frontend"], ["frontend"])

    mock_args = MagicMock()
    mock_args.id = "kai"

    with patch("mempalace.team_cli._get_team_config_path", return_value=str(config_path)):
        cmd_team_remove_user(mock_args)

    saved = json.loads(config_path.read_text())
    assert not any(u["user_id"] == "kai" for u in saved["users"].values())


def test_team_cli_wired_in():
    """team subcommand is registered in main CLI."""
    from mempalace.cli import main
    import sys
    from unittest.mock import patch as mock_patch
    with mock_patch.object(sys, "argv", ["mempalace", "team", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
