"""Validated environment configuration for the store."""

from __future__ import annotations

import os

from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import ProgrammingError

DEFAULT_RESERVATION_MINUTES = 35
MIN_RESERVATION_MINUTES = 31
MAX_RESERVATION_MINUTES = 1440


def store_enabled() -> bool:
    """Return whether the store and its infrastructure should be active."""
    value = os.getenv("STORE_ENABLED", "false").strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError("STORE_ENABLED must be true or false.")


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
            f"Production {name} must use sslmode=require, verify-ca, "
            "or verify-full."
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


def bootstrap_stock() -> int:
    """Return the initial stock assigned during first-time catalog import."""
    value = _integer("STORE_BOOTSTRAP_STOCK", 0)
    if value < 0:
        raise ValueError("STORE_BOOTSTRAP_STOCK must be zero or greater.")
    return value


def validate_store_config() -> None:
    """Fail startup early when enabled store settings are invalid."""
    database_url()
    reservation_minutes()
    bootstrap_stock()
