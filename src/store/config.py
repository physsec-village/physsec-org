"""Validated environment configuration for the store."""

from __future__ import annotations

import os

DEFAULT_RESERVATION_MINUTES = 35
MIN_RESERVATION_MINUTES = 31
MAX_RESERVATION_MINUTES = 1440


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
    """Fail startup early when store numeric settings are invalid."""
    reservation_minutes()
    bootstrap_stock()
