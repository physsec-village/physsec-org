"""Clerk-backed sign-in for the store admin UI.

Clerk's browser SDK signs the user in on /store/admin/login and keeps a
short-lived session JWT in the ``__session`` cookie, refreshing it while an
admin page is open. Every admin request verifies that JWT against the Clerk
instance's signing keys (fetched from Clerk's Backend API and cached by the
SDK, or supplied offline as ``CLERK_JWT_KEY``) and checks that its ``azp``
claim is this site's origin.

A verified session is not enough: the Clerk user must also carry
``{"admin": true}`` in its public metadata. The Clerk instance's session
token is customised to include ``{"metadata": "{{user.public_metadata}}"}``,
so the check reads the verified token and needs no further network call;
revoking the flag takes effect when the token is next refreshed (within a
minute).

Form (CSRF) tokens are HMACs of the Clerk session ID under a per-process
secret, so a token is only valid for the session that rendered the form.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from clerk_backend_api.security import (
    AuthenticateRequestOptions,
    AuthErrorReason,
    Requestish,
    authenticate_request,
)
from starlette.requests import Request

from . import config

logger = logging.getLogger(__name__)

SESSION_COOKIE = "__session"

_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True)
class Session:
    """A verified Clerk session: who is signed in and whether they are an admin."""

    user_id: str
    session_id: str
    admin: bool


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
    metadata = payload.get("metadata")
    admin = isinstance(metadata, dict) and metadata.get("admin") is True
    return Session(user_id=user_id, session_id=session_id, admin=admin)


def current_session(request: Request) -> Session | None:
    """Verify the request's Clerk session once and remember it."""
    if not hasattr(request.state, "admin_session"):
        request.state.admin_session = session_from_request(request)
    return request.state.admin_session


def csrf_token(session: Session) -> str:
    """Return the form token for this session."""
    message = f"store-admin-csrf:{session.session_id}".encode()
    return hmac.new(_SECRET, message, hashlib.sha256).hexdigest()


def valid_csrf(session: Session, token: str) -> bool:
    return hmac.compare_digest(token.encode(), csrf_token(session).encode())
