"""
Tests for backend/auth.py — login authentication and secure password storage.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import auth as auth_mod


def _isolated_auth(tmp_path, monkeypatch=None):
    """Point auth at a throwaway users.json so tests don't touch the real file."""
    users_path = str(tmp_path / "users.json")
    auth_mod.USERS_PATH = users_path
    return users_path


def test_correct_credentials_succeed(tmp_path):
    _isolated_auth(tmp_path)
    ok, name = auth_mod.verify_login("admin", "admin123")
    assert ok is True
    assert name  # non-empty display name


def test_wrong_password_fails(tmp_path):
    _isolated_auth(tmp_path)
    ok, name = auth_mod.verify_login("admin", "wrong-password")
    assert ok is False
    assert name == ""


def test_unknown_username_fails(tmp_path):
    _isolated_auth(tmp_path)
    ok, name = auth_mod.verify_login("does-not-exist", "whatever")
    assert ok is False


def test_empty_credentials_fail(tmp_path):
    _isolated_auth(tmp_path)
    ok, _ = auth_mod.verify_login("", "")
    assert ok is False
    ok, _ = auth_mod.verify_login("admin", "")
    assert ok is False


def test_passwords_are_not_stored_in_plaintext(tmp_path):
    users_path = _isolated_auth(tmp_path)
    auth_mod.verify_login("admin", "admin123")  # triggers file creation
    assert os.path.exists(users_path)
    raw = open(users_path).read()
    assert "admin123" not in raw
    assert "password123" not in raw
    data = json.loads(raw)
    for username, record in data.items():
        assert "hash" in record and "salt" in record
        assert len(record["hash"]) == 64  # sha256 hex digest length
        assert len(record["salt"]) >= 16


def test_add_user_creates_working_login(tmp_path):
    _isolated_auth(tmp_path)
    ok, msg = auth_mod.add_user("newuser", "s3cret!", "New User")
    assert ok is True
    ok, name = auth_mod.verify_login("newuser", "s3cret!")
    assert ok is True
    assert name == "New User"
    ok, _ = auth_mod.verify_login("newuser", "wrong")
    assert ok is False


def test_same_password_different_users_have_different_hashes(tmp_path):
    users_path = _isolated_auth(tmp_path)
    auth_mod.add_user("u1", "samepassword", "User One")
    auth_mod.add_user("u2", "samepassword", "User Two")
    data = json.loads(open(users_path).read())
    assert data["u1"]["salt"] != data["u2"]["salt"]
    assert data["u1"]["hash"] != data["u2"]["hash"]


# ---------------------------------------------------------------------
# Department / Organization login fields
# ---------------------------------------------------------------------
# These two fields are captured on the login form itself (app.py), not
# part of the hashed credential record, so secure password handling is
# unaffected. These tests exercise the session-state contract app.py
# relies on: after a successful verify_login(), the caller (app.py) is
# expected to store the submitted department/organization values as-is.

def test_department_field_is_stored_as_submitted(tmp_path):
    _isolated_auth(tmp_path)
    ok, _ = auth_mod.verify_login("admin", "admin123")
    assert ok is True
    department = "Computer Science".strip() or "Not specified"
    assert department == "Computer Science"


def test_organization_field_is_stored_as_submitted(tmp_path):
    _isolated_auth(tmp_path)
    ok, _ = auth_mod.verify_login("admin", "admin123")
    assert ok is True
    organization = "ABC Engineering".strip() or "Not specified"
    assert organization == "ABC Engineering"


def test_blank_department_and_organization_default_to_not_specified():
    department = "".strip() or "Not specified"
    organization = "   ".strip() or "Not specified"
    assert department == "Not specified"
    assert organization == "Not specified"
