"""Team API key authentication: generation, hashing, permission checks."""

import hashlib
import secrets


def generate_api_key() -> str:
    """Generate a new API key: ak_ + 32 random hex chars."""
    return f"ak_{secrets.token_hex(16)}"


def hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key. Used as lookup key in user config."""
    return hashlib.sha256(key.encode()).hexdigest()


def resolve_user(api_key: str, users: dict):
    """Look up user config by API key hash. Returns user dict or None."""
    key_hash = hash_api_key(api_key)
    return users.get(key_hash)


def check_wing_permission(user: dict, wing: str, operation: str) -> bool:
    """Check if user has permission for operation on wing.
    operation is "read" or "write". Returns True if permitted."""
    wings_config = user.get("wings", {})
    allowed = wings_config.get(operation, [])
    if allowed == "*":
        return True
    return wing in allowed
