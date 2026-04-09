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

    def add_user(self, user_id: str, role: str, read_wings: list, write_wings: list) -> str:
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
        users = self._data.get("users", {})
        to_remove = [h for h, u in users.items() if u["user_id"] == user_id]
        if not to_remove:
            raise ValueError(f"User '{user_id}' not found")
        for h in to_remove:
            del users[h]
        self._save()

    def rotate_key(self, user_id: str) -> str:
        users = self._data.get("users", {})
        current_config = None
        for h, u in users.items():
            if u["user_id"] == user_id and "grace_expires" not in u:
                current_config = u
                break
        if current_config is None:
            raise ValueError(f"User '{user_id}' not found")
        grace_expires = (datetime.now() + timedelta(hours=GRACE_PERIOD_HOURS)).isoformat()
        current_config["grace_expires"] = grace_expires
        new_key = generate_api_key()
        new_hash = hash_api_key(new_key)
        users[new_hash] = {
            "user_id": current_config["user_id"],
            "role": current_config["role"],
            "wings": current_config["wings"],
        }
        self._save()
        return new_key

    def get_user_by_id(self, user_id: str):
        for u in self.users.values():
            if u["user_id"] == user_id and "grace_expires" not in u:
                return u
        return None
