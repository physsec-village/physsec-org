from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..dependencies import templates
from . import catalog, db, storefront
from .stripe_client import (
    StripeNotConfigured,
    construct_webhook_event,
    create_checkout_session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/store")
MAX_WEBHOOK_BYTES = 1024 * 1024


class CartItem(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1, le=99)


class CartPayload(BaseModel):
    items: list[CartItem] = Field(min_length=1, max_length=90)
    checkout_id: str | None = Field(default=None, min_length=32, max_length=64)


def _items(payload: CartPayload) -> list[dict[str, Any]]:
    return [{"sku": item.sku, "qty": item.qty} for item in payload.items]


def _context(
    catalog_products: tuple[storefront.ProductView, ...], **extra: Any
) -> dict[str, Any]:
    return {
        "catalog_json": storefront.browser_catalog(catalog_products),
        **extra,
    }


@router.get("", response_class=HTMLResponse, name="store_page")
def store_page(request: Request):
    products = storefront.products()
    featured = storefront.featured_products(products)
    if not products:
        raise HTTPException(status_code=503, detail="Store catalog is unavailable.")
    hero = next(
        (product for product in products if product.id == catalog.HERO_PRODUCT_ID),
        products[0],
    )
    return templates.TemplateResponse(
        request=request,
        name="pages/store/home.html",
        context=_context(
            products,
            hero=hero,
            featured=featured[:4],
            categories=storefront.category_hub(products),
        ),
    )


@router.get("/catalog", response_class=HTMLResponse, name="store_catalog_page")
def store_catalog_page(request: Request, cat: str = "All"):
    if cat not in catalog.CATEGORY_LABELS:
        cat = "All"
    products = storefront.products()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/catalog.html",
        context=_context(
            products,
            products=products,
            categories=storefront.category_hub(products),
            initial_cat=cat,
            all_blurb=catalog.ALL_PRODUCTS_BLURB,
        ),
    )


@router.get(
    "/product/{product_id}", response_class=HTMLResponse, name="store_product_page"
)
def store_product_page(request: Request, product_id: str):
    product = storefront.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    products = storefront.products()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/product.html",
        context=_context(
            products,
            product=product,
            related=storefront.related_products(product, products),
        ),
    )


@router.get("/checkout", response_class=HTMLResponse, name="store_checkout_page")
def store_checkout_page(request: Request):
    products = storefront.products()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/checkout.html",
        context=_context(products),
    )


@router.post("/api/cart-info")
def store_cart_info(payload: CartPayload):
    normalized, problems = db.normalize_cart(_items(payload))
    return {"items": normalized, "problems": problems}


@router.post("/checkout")
def store_checkout(payload: CartPayload):
    ttl_minutes = int(os.getenv("STORE_RESERVATION_MINUTES", "30"))
    try:
        if payload.checkout_id:
            checkout = db.get_checkout(payload.checkout_id)
            if checkout is None or checkout["status"] != "creating":
                raise db.CheckoutConflict("Checkout is not retryable.")
        else:
            db.cleanup_expired_reservations(limit=100)
            checkout = db.reserve_checkout(_items(payload), ttl_minutes=ttl_minutes)
        session = create_checkout_session(checkout)
        session_expires_at = datetime.fromtimestamp(session.expires_at, tz=UTC)
        db.attach_stripe_session(
            checkout["id"], session.id, expires_at=session_expires_at
        )
        logger.info(
            "store_checkout_opened checkout_id=%s stripe_session_id=%s",
            checkout["id"],
            session.id,
        )
        return {"url": session.url, "checkout_id": checkout["id"]}
    except db.CartUnavailable as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Some cart items are no longer available.",
                "problems": exc.problems,
            },
        )
    except db.CheckoutConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except StripeNotConfigured:
        if "checkout" in locals() and checkout.get("id"):
            db.mark_provider_failure(checkout["id"], "not_configured")
        return JSONResponse(
            status_code=503,
            content={"detail": "Store checkout is not configured yet."},
        )
    except (stripe.InvalidRequestError, stripe.AuthenticationError) as exc:
        if "checkout" in locals() and checkout.get("id"):
            db.mark_provider_failure(checkout["id"], type(exc).__name__)
        logger.exception("store_checkout_provider_rejected")
        return JSONResponse(
            status_code=502,
            content={"detail": "Checkout could not be started. Please try again."},
        )
    except stripe.StripeError:
        checkout_id = checkout.get("id") if "checkout" in locals() else None
        logger.exception(
            "store_checkout_provider_uncertain checkout_id=%s", checkout_id
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": "Checkout status is uncertain. Retrying is safe.",
                "checkout_id": checkout_id,
                "retryable": bool(checkout_id),
            },
        )


@router.get("/confirmed", response_class=HTMLResponse, name="store_confirmed_page")
def store_confirmed_page(request: Request, session_id: str = ""):
    if not session_id:
        raise HTTPException(status_code=404)
    order = db.confirmation_lookup(session_id)
    products = storefront.products()
    pending = order is None
    return templates.TemplateResponse(
        request=request,
        name="pages/store/confirmed.html",
        context=_context(
            products,
            order=order,
            pending=pending,
            session_id=session_id,
        ),
    )


@router.post("/webhook", include_in_schema=False)
async def store_webhook(request: Request):
    content_length = request.headers.get("content-length")
    try:
        declared_length = int(content_length) if content_length else 0
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid webhook."})
    if declared_length > MAX_WEBHOOK_BYTES:
        return JSONResponse(
            status_code=413, content={"detail": "Webhook is too large."}
        )
    chunks: list[bytes] = []
    payload_size = 0
    async for chunk in request.stream():
        payload_size += len(chunk)
        if payload_size > MAX_WEBHOOK_BYTES:
            return JSONResponse(
                status_code=413, content={"detail": "Webhook is too large."}
            )
        chunks.append(chunk)
    payload = b"".join(chunks)
    try:
        event = construct_webhook_event(
            payload, request.headers.get("stripe-signature")
        )
    except StripeNotConfigured, ValueError, stripe.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"detail": "Invalid webhook."})

    event_id = str(event["id"])
    event_type = str(event["type"])
    event_object = event["data"]["object"]
    if hasattr(event_object, "to_dict_recursive"):
        event_object = event_object.to_dict_recursive()
    try:
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            if event_object.get("payment_status") != "paid":
                result = await run_in_threadpool(
                    db.process_ignored_event,
                    event_id,
                    event_type,
                    object_id=str(event_object.get("id") or ""),
                    stripe_created_at=event.get("created"),
                    payload=payload,
                )
            else:
                result = await run_in_threadpool(
                    db.process_paid_event,
                    event_id,
                    event_object,
                    event_type=event_type,
                    stripe_created_at=event.get("created"),
                    payload=payload,
                )
        elif event_type == "checkout.session.expired":
            result = await run_in_threadpool(
                db.process_expired_event, event_id, event_object
            )
        elif event_type == "charge.refunded":
            result = await run_in_threadpool(
                db.process_refund_event, event_id, event_object
            )
        else:
            result = await run_in_threadpool(
                db.process_ignored_event,
                event_id,
                event_type,
                object_id=str(event_object.get("id") or ""),
                stripe_created_at=event.get("created"),
                payload=payload,
            )
        logger.info(
            "store_webhook_processed event_id=%s event_type=%s result=%s",
            event_id,
            event_type,
            result,
        )
        return {"received": True}
    except db.CheckoutConflict as exc:
        await run_in_threadpool(
            db.record_event_failure,
            event_id,
            event_type,
            "checkout_conflict",
            str(exc),
            object_id=str(event_object.get("id") or ""),
        )
        logger.exception(
            "store_webhook_failed event_id=%s event_type=%s",
            event_id,
            event_type,
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "Webhook processing must be retried."},
        )
