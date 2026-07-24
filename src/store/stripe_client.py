from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import stripe


class StripeNotConfigured(RuntimeError):
    """Raised when checkout cannot safely be enabled."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise StripeNotConfigured(f"{name} is not configured.")
    return value


def create_checkout_session(checkout: dict[str, Any]) -> stripe.checkout.Session:
    """Create or recover a hosted Checkout Session for a reserved cart."""
    stripe.api_key = _required("STRIPE_SECRET_KEY")
    origin = _required("STORE_PUBLIC_ORIGIN").rstrip("/")
    countries = [
        value.strip().upper()
        for value in os.getenv("STORE_SHIP_COUNTRIES", "US,CA").split(",")
        if value.strip()
    ]
    if not countries:
        raise StripeNotConfigured("STORE_SHIP_COUNTRIES must not be empty.")

    line_items = []
    for item in checkout["items"]:
        name = item["product_name"]
        if item.get("variant_name"):
            name = f"{name} — {item['variant_name']}"
        line_items.append(
            {
                "quantity": item["quantity"],
                "price_data": {
                    "currency": checkout["currency"],
                    "unit_amount": item["unit_amount_cents"],
                    "product_data": {
                        "name": name,
                        "metadata": {"sku": item["sku"]},
                    },
                },
            }
        )

    checkout_id = checkout["id"]
    expires_at = datetime.fromisoformat(checkout["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": line_items,
        "client_reference_id": checkout_id,
        "metadata": {"checkout_id": checkout_id},
        "success_url": (f"{origin}/store/confirmed?session_id={{CHECKOUT_SESSION_ID}}"),
        "cancel_url": f"{origin}/store/checkout",
        "shipping_address_collection": {"allowed_countries": countries},
        "expires_at": int(expires_at.timestamp()),
    }
    shipping_rate_ids = [
        value.strip()
        for value in os.getenv("STRIPE_SHIPPING_RATE_IDS", "").split(",")
        if value.strip()
    ]
    if shipping_rate_ids:
        params["shipping_options"] = [
            {"shipping_rate": rate_id} for rate_id in shipping_rate_ids
        ]
    if os.getenv("STORE_AUTOMATIC_TAX", "").lower() == "true":
        params["automatic_tax"] = {"enabled": True}

    return stripe.checkout.Session.create(
        **params,
        idempotency_key=f"checkout:{checkout_id}",
    )


def construct_webhook_event(payload: bytes, signature: str | None) -> stripe.Event:
    """Verify and decode a Stripe webhook payload."""
    stripe.api_key = _required("STRIPE_SECRET_KEY")
    return stripe.Webhook.construct_event(
        payload,
        signature,
        _required("STRIPE_WEBHOOK_SECRET"),
    )
