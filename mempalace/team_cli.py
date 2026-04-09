"""CLI subcommands for team management."""

import json
import os

from .config import MempalaceConfig
from .team_config import TeamServerConfig


def _get_team_config_path():
    return os.path.expanduser("/var/mempalace-team/team_config.json")


def cmd_team_init(args):
    cfg = MempalaceConfig()
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
    cfg = MempalaceConfig()
    if not cfg.team_enabled:
        print("  Team layer: not configured")
        return
    print(f"  Server: {cfg.team_server}")
    print(f"  Timeout: {cfg.team_timeout}s")
    import asyncio
    from .team_client import TeamClient
    client = TeamClient(server_url=cfg.team_server, api_key=cfg.team_api_key, timeout=cfg.team_timeout)
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(client.status())
    loop.run_until_complete(client.close())
    loop.close()
    if "team" in result:
        print(f"  Status: {result['team']}")
    else:
        print(f"  Status: connected")
        print(f"  Server version: {result.get('version', '?')}")
        print(f"  Total drawers: {result.get('total_drawers', '?')}")


def cmd_team_whoami(args):
    cfg = MempalaceConfig()
    if not cfg.team_enabled:
        print("  Team layer: not configured")
        return
    import asyncio
    from .team_client import TeamClient
    client = TeamClient(server_url=cfg.team_server, api_key=cfg.team_api_key, timeout=cfg.team_timeout)
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(client.status())
    loop.run_until_complete(client.close())
    loop.close()
    if "team" in result:
        print(f"  Status: {result['team']}")
    else:
        print(f"  User: {result.get('user', '?')}")


def cmd_team_serve(args):
    import uvicorn
    from .team_server import create_app
    config_path = getattr(args, "config", None) or _get_team_config_path()
    data_dir = getattr(args, "data_dir", None) or "/var/mempalace-team/data"
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8900)
    app = create_app(config_path=config_path, data_dir=data_dir)
    print(f"  MemPalace Team Server starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def cmd_team_add_user(args):
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    read_wings = [w.strip() for w in args.read_wings.split(",")]
    write_wings = [w.strip() for w in args.write_wings.split(",")]
    api_key = cfg.add_user(user_id=args.id, role=args.role, read_wings=read_wings, write_wings=write_wings)
    print(f"  User '{args.id}' added ({args.role})")
    print(f"  API Key: {api_key}")
    print(f"  (shown once — save it now)")


def cmd_team_remove_user(args):
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    cfg.remove_user(args.id)
    print(f"  User '{args.id}' removed")


def cmd_team_rotate_key(args):
    config_path = _get_team_config_path()
    cfg = TeamServerConfig(config_path=config_path)
    new_key = cfg.rotate_key(args.id)
    print(f"  New key for '{args.id}': {new_key}")
    print(f"  Old key valid for 24 hours")


TEAM_COMMANDS = {
    "init": cmd_team_init,
    "status": cmd_team_status,
    "whoami": cmd_team_whoami,
    "serve": cmd_team_serve,
    "add-user": cmd_team_add_user,
    "remove-user": cmd_team_remove_user,
    "rotate-key": cmd_team_rotate_key,
}
