"""
auth.py
Minimal username/password authentication for CAD Studio.

Passwords are never stored in plain text. Each user record stores a
random per-user salt and a PBKDF2-HMAC-SHA256 hash (100,000 iterations)
of "salt + password", computed with hashlib from the Python standard
library only (no extra dependency).

User records live in backend/users.json. A small default set of demo
accounts is created on first run if the file does not exist yet.
"""
from __future__ import annotations
import hashlib
import json
import os
import secrets

USERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
PBKDF2_ITERATIONS = 100_000


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"),
                              PBKDF2_ITERATIONS)
    return dk.hex()


def _default_users() -> dict:
    """Demo accounts created only if users.json does not exist yet."""
    users = {}
    for username, password, display_name in [
        ("admin", "admin123", "Administrator"),
        ("sai", "password123", "Sai Teja"),
    ]:
        salt = secrets.token_hex(16)
        users[username] = {
            "display_name": display_name,
            "salt": salt,
            "hash": _hash_password(password, salt),
        }
    return users


def _load_users() -> dict:
    if not os.path.exists(USERS_PATH):
        users = _default_users()
        _save_users(users)
        return users
    with open(USERS_PATH, "r") as f:
        return json.load(f)


def _save_users(users: dict):
    with open(USERS_PATH, "w") as f:
        json.dump(users, f, indent=2)


def verify_login(username: str, password: str) -> tuple[bool, str]:
    """
    Returns (ok, display_name). display_name falls back to username
    if not set. Never reveals whether the username or password was wrong.
    """
    if not username or not password:
        return False, ""
    users = _load_users()
    record = users.get(username)
    if record is None:
        return False, ""
    computed = _hash_password(password, record["salt"])
    # constant-time compare
    if secrets.compare_digest(computed, record["hash"]):
        return True, record.get("display_name", username)
    return False, ""


def add_user(username: str, password: str, display_name: str | None = None) -> tuple[bool, str]:
    """Create or update a user account with a securely hashed password."""
    if not username or not password:
        return False, "Username and password are required."
    users = _load_users()
    salt = secrets.token_hex(16)
    users[username] = {
        "display_name": display_name or username,
        "salt": salt,
        "hash": _hash_password(password, salt),
    }
    _save_users(users)
    return True, f"User '{username}' saved."
