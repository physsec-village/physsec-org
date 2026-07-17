import os
from typing import Any

import stripe
from fastapi import Request

from . import db

class StripeNotConfigured(RuntimeError):
    pass


def _base_url(request: Request) -> str:
    origin = os.getenv("STORE_PUBLIC_ORIGIN", "").strip()
    if not origin:
        raise StripeNotConfigured("Store public origin is not configured.")
    return origin.rstrip("/")


def create_checkout_session(request: Request, items: list[dict[str, Any]]) -> stripe.checkout.Session:
    """Create a Stripe Checkout Session for already-validated cart items.

    ``items`` must be catalog-resolved rows from
    ``db.get_variants_for_checkout`` (names, prices, and quantities taken
    from the database) — never caller-supplied values.
    """
    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        raise StripeNotConfigured("Store checkout is not configured yet.")

    stripe.api_key = secret_key
    cart_id = db.create_checkout_cart(items)
    allowed_countries = [
        country.strip().upper()
        for country in os.getenv("STORE_SHIP_COUNTRIES", "US,CA").split(",")
        if country.strip()
    ]
    shipping_rate_ids = [
        rate_id.strip()
        for rate_id in os.getenv("STRIPE_SHIPPING_RATE_IDS", "").split(",")
        if rate_id.strip()
    ]

    line_items = []
    for item in items:
        product_name = item["product_name"]
        if item["variant_name"]:
            product_name = f"{product_name} — {item['variant_name']}"
        line_items.append(
            {
                "quantity": int(item["qty"]),
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(item["price_cents"]),
                    "product_data": {
                        "name": product_name,
                        "metadata": {"sku": item["sku"]},
                    },
                },
            }
        )

    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": line_items,
        "metadata": {"cart_id": cart_id},
        "client_reference_id": cart_id,
        # The literal {CHECKOUT_SESSION_ID} placeholder is filled in by Stripe;
        # the success page only clears the cart when the param is present.
        "success_url": f"{_base_url(request)}/store/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{_base_url(request)}/store/cart",
        "shipping_address_collection": {"allowed_countries": allowed_countries},
    }
    if shipping_rate_ids:
        params["shipping_options"] = [{"shipping_rate": rate_id} for rate_id in shipping_rate_ids]
    # Requires Stripe Tax to be enabled on the account, so it is opt-in.
    if os.getenv("STORE_AUTOMATIC_TAX") == "true":
        params["automatic_tax"] = {"enabled": True}

    return stripe.checkout.Session.create(**params)


def verify_checkout_session(session_id: str) -> bool:
    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        return False
    stripe.api_key = secret_key
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:
        return False
    return session.get("payment_status") == "paid"


def construct_webhook_event(payload: bytes, signature: str | None) -> stripe.Event:
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise StripeNotConfigured("Stripe webhook is not configured.")
    return stripe.Webhook.construct_event(payload, signature, webhook_secret)
