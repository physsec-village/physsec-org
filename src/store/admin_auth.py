"""Placeholder sign-in for the store admin UI.

TEMPORARY: the credentials are hardcoded (admin/admin) so the dev deployment
can be explored. Replace this module with a real login before merging to main.

A successful sign-in sets a session cookie signed with a per-process secret,
so sessions end whenever the app restarts (including every deploy).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

USERNAME = "admin"
PASSWORD = "admin"
SESSION_COOKIE = "psv_store_admin"

_SECRET = secrets.token_bytes(32)


def _sign(purpose: str) -> str:
    return hmac.new(_SECRET, purpose.encode(), hashlib.sha256).hexdigest()


def check_credentials(username: str, password: str) -> bool:
    username_ok = hmac.compare_digest(username.encode(), USERNAME.encode())
    password_ok = hmac.compare_digest(password.encode(), PASSWORD.encode())
    return username_ok and password_ok


def session_token() -> str:
    return _sign("store-admin-session")


def valid_session(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token.encode(), session_token().encode())


def csrf_token() -> str:
    return _sign("store-admin-csrf")


def valid_csrf(token: str) -> bool:
    return hmac.compare_digest(token.encode(), csrf_token().encode())
