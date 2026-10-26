"""Validated environment configuration for the store."""

from __future__ import annotations

import base64
import binascii
import os

from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import ProgrammingError

DEFAULT_RESERVATION_MINUTES = 35
MIN_RESERVATION_MINUTES = 31
MAX_RESERVATION_MINUTES = 1440


def _env_flag(name: str) -> bool:
    """Return a boolean environment variable, treating unset as false."""
    value = os.getenv(name, "false").strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def store_enabled() -> bool:
    """Return whether the store and its infrastructure should be active."""
    return _env_flag("STORE_ENABLED")


def store_published() -> bool:
    """Return whether the enabled store is open to the public.

    Until this is true, the storefront is a preview that only signed-in
    admins can reach; everyone else sees the store as if it were disabled.
    Unset means unpublished, so forgetting the flag never exposes the store.
    """
    return _env_flag("STORE_PUBLISHED")


def _postgres_url(name: str) -> str:
    """Return a validated PostgreSQL connection string from the environment."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    if not value.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"{name} must be a PostgreSQL connection string.")
    try:
        parameters = conninfo_to_dict(value)
    except ProgrammingError as exc:
        raise ValueError(
            f"{name} is not a valid PostgreSQL connection string."
        ) from exc
    if os.getenv("APP_ENV", "development").lower() == "production" and parameters.get(
        "sslmode"
    ) not in {"require", "verify-ca", "verify-full"}:
        raise ValueError(
            f"Production {name} must use sslmode=require, verify-ca, or verify-full."
        )
    return value


def database_url() -> str:
    """Return the server-side PostgreSQL connection string."""
    return _postgres_url("DATABASE_URL")


def migration_database_url() -> str:
    """Return the owner PostgreSQL connection string used for migrations."""
    return _postgres_url("MIGRATION_DATABASE_URL")


def _integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def reservation_minutes() -> int:
    """Return a Stripe-safe inventory reservation lifetime."""
    value = _integer("STORE_RESERVATION_MINUTES", DEFAULT_RESERVATION_MINUTES)
    if not MIN_RESERVATION_MINUTES <= value <= MAX_RESERVATION_MINUTES:
        raise ValueError(
            "STORE_RESERVATION_MINUTES must be between "
            f"{MIN_RESERVATION_MINUTES} and {MAX_RESERVATION_MINUTES}."
        )
    return value


def public_origin() -> str:
    """Return the site origin browsers use, as Clerk reports it in ``azp``."""
    value = os.getenv("STORE_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if not value.startswith(("https://", "http://")) or "/" in value.split("://", 1)[1]:
        raise ValueError(
            "STORE_PUBLIC_ORIGIN must be an origin like https://physsec.org."
        )
    return value


def clerk_publishable_key() -> str:
    """Return the Clerk publishable key the browser SDK is loaded with."""
    value = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
    if not value.startswith(("pk_test_", "pk_live_")):
        raise ValueError("CLERK_PUBLISHABLE_KEY must be a Clerk publishable key.")
    return value


def clerk_secret_key() -> str:
    """Return the Clerk secret key used for signing-key and user lookups."""
    value = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not value.startswith(("sk_test_", "sk_live_")):
        raise ValueError("CLERK_SECRET_KEY must be a Clerk secret key.")
    return value


def clerk_jwt_key() -> str | None:
    """Return the optional PEM public key for offline session verification."""
    value = os.getenv("CLERK_JWT_KEY", "").strip()
    if value and "-----BEGIN PUBLIC KEY-----" not in value:
        raise ValueError("CLERK_JWT_KEY must be a PEM public key.")
    return value or None


def clerk_frontend_api() -> str:
    """Return the Clerk Frontend API host encoded in the publishable key.

    The browser SDK is served from this host, e.g. ``clerk.physsec.org`` for
    a production instance or ``*.clerk.accounts.dev`` for a development one.
    """
    encoded = clerk_publishable_key().split("_", 2)[2]
    try:
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("CLERK_PUBLISHABLE_KEY is not a valid Clerk key.") from exc
    if not host.endswith("$") or "/" in host:
        raise ValueError("CLERK_PUBLISHABLE_KEY is not a valid Clerk key.")
    return host[:-1]


def validate_store_config() -> None:
    """Fail startup early when enabled store settings are invalid."""
    database_url()
    reservation_minutes()
    public_origin()
    clerk_frontend_api()
    clerk_secret_key()
    clerk_jwt_key()
