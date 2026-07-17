from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from stripe import SignatureVerificationError, StripeError

from starlette.concurrency import run_in_threadpool

from ..dependencies import templates
from . import db
from .stripe_client import (
    StripeNotConfigured,
    construct_webhook_event,
    create_checkout_session,
    verify_checkout_session,
)

router = APIRouter(prefix="/store")


class CartItem(BaseModel):
    sku: str
    qty: int = Field(default=1)


class CartPayload(BaseModel):
    items: list[CartItem] = Field(max_length=200)


def cents(value: int) -> str:
    return f"${(value or 0) / 100:.2f}"


def product_price(product: dict[str, Any]) -> str:
    if product.get("price_varies"):
        return f"From {cents(product['min_price_cents'])}"
    return cents(product.get("price_cents", 0))


@router.get("", response_class=HTMLResponse, name="store_page")
def store_page(request: Request):
    featured = db.get_published_products(featured=True)
    products = db.get_published_products()
    return templates.TemplateResponse(
        request=request,
        name="pages/store.html",
        context={
            "featured_products": featured,
            "products": products,
            "cents": cents,
            "product_price": product_price,
        },
    )


@router.get("/products/{slug}", response_class=HTMLResponse, name="store_product_page")
def store_product_page(request: Request, slug: str):
    product = db.get_product_by_slug(slug, published_only=True)
    if product is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="pages/store-product.html",
        context={"product": product, "cents": cents, "product_price": product_price},
    )


@router.get("/cart", response_class=HTMLResponse, name="store_cart_page")
def store_cart_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/store-cart.html")


@router.post("/api/cart-info")
def store_cart_info(payload: CartPayload):
    items = [{"sku": item.sku, "qty": item.qty} for item in payload.items]
    normalized, removed = db.get_cart_items(items)
    return {"items": normalized, "removed": removed}


@router.post("/checkout")
def store_checkout(request: Request, payload: CartPayload):
    if not payload.items:
        return JSONResponse(status_code=400, content={"detail": "Cart is empty."})
    distinct_skus = {item.sku.strip().upper() for item in payload.items if item.sku.strip()}
    if len(distinct_skus) > 90:
        return JSONResponse(
            status_code=400,
            content={"detail": "Please check out with 90 or fewer distinct items."},
        )

    requested = [{"sku": item.sku, "qty": item.qty} for item in payload.items]
    items, problems = db.get_variants_for_checkout(requested)
    if problems or not items:
        return JSONResponse(
            status_code=409,
            content={"detail": "Some cart items are no longer available.", "problems": problems},
        )

    try:
        session = create_checkout_session(request, items)
    except StripeNotConfigured:
        return JSONResponse(
            status_code=503,
            content={"detail": "Store checkout is not configured yet."},
        )
    except StripeError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Checkout could not be started. Please try again."},
        )
    return {"url": session.url}


@router.get("/success", response_class=HTMLResponse, name="store_success_page")
def store_success_page(request: Request, session_id: str | None = None):
    confirmed = bool(session_id) and verify_checkout_session(session_id)
    return templates.TemplateResponse(
        request=request,
        name="pages/store-success.html",
        context={"confirmed": confirmed},
    )


@router.post("/webhook")
async def store_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        event = construct_webhook_event(payload, signature)
    except (StripeNotConfigured, SignatureVerificationError, ValueError):
        return JSONResponse(status_code=400, content={"detail": "Invalid Stripe webhook."})

    if event["type"] == "charge.refunded":
        status = await run_in_threadpool(
            db.record_refund_from_charge, event["data"]["object"]
        )
        if status is None:
            # A refund can race the checkout event. A non-2xx response asks
            # Stripe to retry instead of permanently dropping the update.
            return JSONResponse(
                status_code=409,
                content={"detail": "Checkout order has not been recorded yet."},
            )
        return {"received": True}

    # async_payment_succeeded covers delayed payment methods (e.g. bank
    # debits) that complete after checkout.session.completed fires unpaid.
    if event["type"] not in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        return {"received": True}

    session = event["data"]["object"]
    if session.get("payment_status") != "paid":
        return {"received": True}

    metadata = session.get("metadata") or {}
    cart_id = metadata.get("cart_id") or session.get("client_reference_id")
    if not cart_id:
        return {"received": True}
    # This handler is async, so keep blocking sqlite work off the event loop.
    cart = await run_in_threadpool(db.get_checkout_cart, cart_id)
    if cart is None:
        return {"received": True}
    await run_in_threadpool(db.record_order_from_session, session, cart)
    return {"received": True}
