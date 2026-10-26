"""Clerk-backed sign-in for the store admin UI.

Clerk's browser SDK signs the user in on /store/admin/login and keeps a
short-lived session JWT in the ``__session`` cookie, refreshing it while an
admin page is open. Every admin request verifies that JWT against the Clerk
instance's signing keys (fetched from Clerk's Backend API and cached by the
SDK, or supplied offline as ``CLERK_JWT_KEY``) and checks that its ``azp``
claim is this site's origin.

A verified session is not enough: the Clerk user must also carry
``{"admin": true}`` in its public metadata, which is looked up through the
Backend API and cached for a minute so revoking admin access takes effect
promptly without a lookup on every request.

Form (CSRF) tokens are HMACs of the Clerk session ID under a per-process
secret, so a token is only valid for the session that rendered the form.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass

from clerk_backend_api import Clerk
from clerk_backend_api.security import (
    AuthenticateRequestOptions,
    AuthErrorReason,
    Requestish,
    authenticate_request,
)

from . import config

logger = logging.getLogger(__name__)

SESSION_COOKIE = "__session"
ADMIN_CACHE_SECONDS = 60

_SECRET = secrets.token_bytes(32)
# user_id -> (is_admin, monotonic expiry)
_admin_cache: dict[str, tuple[bool, float]] = {}


@dataclass(frozen=True)
class Session:
    """A verified Clerk session: who is signed in and which session it is."""

    user_id: str
    session_id: str


class AdminLookupError(Exception):
    """Clerk's Backend API could not say whether the user is an admin."""


def session_from_request(request: Requestish) -> Session | None:
    """Return the verified Clerk session on the request, or None."""
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=config.clerk_secret_key(),
            jwt_key=config.clerk_jwt_key(),
            authorized_parties=[config.public_origin()],
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in:
        if state.reason is not AuthErrorReason.SESSION_TOKEN_MISSING:
            logger.info("store_admin_session_rejected reason=%s", state.message)
        return None
    payload = state.payload or {}
    user_id = payload.get("sub")
    session_id = payload.get("sid")
    if not isinstance(user_id, str) or not isinstance(session_id, str):
        logger.warning("store_admin_session_rejected reason=missing sub or sid")
        return None
    return Session(user_id=user_id, session_id=session_id)


def public_metadata(user_id: str) -> dict:
    """Fetch a user's public metadata from Clerk's Backend API."""
    user = Clerk(bearer_auth=config.clerk_secret_key()).users.get(user_id=user_id)
    metadata = user.public_metadata
    return metadata if isinstance(metadata, dict) else {}


def is_admin(user_id: str) -> bool:
    """Return whether the Clerk user's public metadata has ``admin: true``.

    Results are cached for ADMIN_CACHE_SECONDS. Raises AdminLookupError when
    the Backend API cannot be reached, so an outage is not mistaken for a
    revoked admin.
    """
    now = time.monotonic()
    cached = _admin_cache.get(user_id)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        admin = public_metadata(user_id).get("admin") is True
    except Exception as exc:
        raise AdminLookupError("Clerk user lookup failed.") from exc
    for key in [key for key, (_, expiry) in _admin_cache.items() if expiry <= now]:
        del _admin_cache[key]
    _admin_cache[user_id] = (admin, now + ADMIN_CACHE_SECONDS)
    return admin


def csrf_token(session: Session) -> str:
    """Return the form token for this session."""
    message = f"store-admin-csrf:{session.session_id}".encode()
    return hmac.new(_SECRET, message, hashlib.sha256).hexdigest()


def valid_csrf(session: Session, token: str) -> bool:
    return hmac.compare_digest(token.encode(), csrf_token(session).encode())
