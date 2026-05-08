import os

import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


def create_checkout_session(line_items, success_url, cancel_url):
    if not stripe.api_key:
        return success_url.replace("{CHECKOUT_SESSION_ID}", "stub_session_local")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url
