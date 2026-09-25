from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..dependencies import templates
from . import catalog, db, storefront
from .config import reservation_minutes
from .stripe_client import (
    StripeNotConfigured,
    construct_webhook_event,
    create_checkout_session,
)

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1024 * 1024


def require_store_enabled(request: Request) -> None:
    """Hide every store endpoint until its infrastructure is enabled."""
    if not request.app.state.store_enabled:
        raise HTTPException(status_code=404)


router = APIRouter(
    prefix="/store",
    dependencies=[Depends(require_store_enabled)],
)


class CartItem(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1, le=99)


class CartPayload(BaseModel):
    items: list[CartItem] = Field(min_length=1, max_length=90)
    checkout_id: str | None = Field(default=None, min_length=32, max_length=64)


def _items(payload: CartPayload) -> list[dict[str, Any]]:
    """Normalize the cart and refuse items that need vetting.

    `products.published` is the database-side guard, but the menu's
    restricted flag is enforced here too so a row that was published by an
    earlier import or by hand can still never be checked out.
    """
    items = [
        {"sku": item.sku.strip().upper(), "qty": item.qty} for item in payload.items
    ]
    restricted = [
        {"sku": item["sku"], "reason": "restricted"}
        for item in items
        if _is_restricted(item["sku"])
    ]
    if restricted:
        raise db.CartUnavailable(restricted)
    return items


def _is_restricted(sku: str) -> bool:
    """True when the SKU, or the family it belongs to, needs vetting.

    A legacy or hand-made family product can carry `PSV-KYS-023-001` style
    variants under a restricted base SKU, so the check covers both.
    """
    candidates = {sku}
    parts = sku.split("-")
    if len(parts) == 4:
        candidates.add("-".join(parts[:3]))
    return any(
        (entry := catalog.ITEMS_BY_SKU.get(candidate)) is not None and entry.restricted
        for candidate in candidates
    )


def _context(front: storefront.Storefront, **extra: Any) -> dict[str, Any]:
    return {
        "catalog_json": front.browser_catalog(),
        "collections": front.collections(),
        **extra,
    }


@router.get("", response_class=HTMLResponse, name="store_page")
def store_page(request: Request):
    front = storefront.Storefront()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/home.html",
        context=_context(
            front,
            hero=front.view(catalog.HERO),
            featured=front.views(catalog.FEATURED),
        ),
    )


@router.get("/catalog", include_in_schema=False)
def store_catalog_redirect(request: Request):
    """The single-grid catalog was replaced by per-collection pages."""
    return RedirectResponse(request.url_for("store_page"), status_code=301)


@router.get(
    "/collection/{slug}", response_class=HTMLResponse, name="store_collection_page"
)
def store_collection_page(request: Request, slug: str):
    collection = catalog.COLLECTION_MAP.get(slug)
    if collection is None:
        raise HTTPException(status_code=404)
    front = storefront.Storefront()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/collection.html",
        context=_context(front, collection=front.collection(collection)),
    )


@router.get("/product/{slug}", response_class=HTMLResponse, name="store_product_page")
def store_product_page(request: Request, slug: str):
    item = catalog.ITEMS_BY_SLUG.get(slug)
    if item is None:
        raise HTTPException(status_code=404)
    front = storefront.Storefront()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/product.html",
        context=_context(
            front,
            product=front.view(item),
            collection=front.collection(catalog.collection_for(item)),
            group=catalog.group_for(item),
            related=front.views(catalog.related_items(item)),
        ),
    )


@router.get("/search", response_class=HTMLResponse, name="store_search_page")
def store_search_page(request: Request, q: str = Query(default="", max_length=80)):
    query = " ".join(q.split())
    front = storefront.Storefront()
    return templates.TemplateResponse(
        request=request,
        name="pages/store/search.html",
        context=_context(
            front,
            query=query,
            results=front.views(catalog.search(query)),
        ),
    )


@router.get("/checkout", response_class=HTMLResponse, name="store_checkout_page")
def store_checkout_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/store/checkout.html",
        context=_context(storefront.Storefront()),
    )


@router.post("/api/cart-info")
def store_cart_info(payload: CartPayload):
    try:
        normalized, problems = db.normalize_cart(_items(payload))
    except db.CartUnavailable as exc:
        return {"items": [], "problems": exc.problems}
    return {"items": normalized, "problems": problems}


@router.post("/checkout")
def store_checkout(payload: CartPayload):
    try:
        ttl_minutes = reservation_minutes()
        if payload.checkout_id:
            checkout = db.get_checkout(payload.checkout_id)
            if checkout is None or checkout["status"] != "creating":
                raise db.CheckoutConflict("Checkout is not retryable.")
            expires_at = datetime.fromisoformat(checkout["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC) + timedelta(minutes=30):
                db.mark_provider_failure(checkout["id"], "stripe_retry_window_elapsed")
                raise db.CheckoutConflict("Checkout reservation has expired.")
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
    except ValueError as exc:
        if "checkout" in locals() and checkout.get("id"):
            db.mark_provider_failure(checkout["id"], "invalid_store_configuration")
        logger.error("store_checkout_configuration_invalid error=%s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "Store checkout configuration is invalid."},
        )
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
    pending = order is None
    return templates.TemplateResponse(
        request=request,
        name="pages/store/confirmed.html",
        context=_context(
            storefront.Storefront(),
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
