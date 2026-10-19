"""Basic store administration UI: products, variants, stock, and orders.

The UI is hidden (404) unless the store is enabled and admin credentials are
configured. Requests authenticate with HTTP Basic; because browsers resend
Basic credentials on cross-site requests, every form carries a CSRF token
derived from the configured credentials.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import ValidationError

from ..dependencies import templates
from . import db
from .admin_auth import AdminCredentials, admin_credentials
from .models import (
    ProductInput,
    VariantInput,
    VariantUpdate,
    cents_from_dollars,
    dollars_from_cents,
)
from .router import require_store_enabled

logger = logging.getLogger(__name__)

MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 300
_failures: dict[str, deque[float]] = {}
_failures_lock = threading.Lock()
_basic = HTTPBasic(auto_error=False, realm="PSV store admin")

NOTICES = {
    "saved": "Changes saved.",
    "created": "Product created.",
    "variant": "Variant added.",
}


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttled(client: str, now: float) -> bool:
    with _failures_lock:
        attempts = _failures.get(client)
        if not attempts:
            return False
        while attempts and attempts[0] <= now - FAILURE_WINDOW_SECONDS:
            attempts.popleft()
        if not attempts:
            del _failures[client]
            return False
        return len(attempts) >= MAX_FAILURES


def _record_failure(client: str, now: float) -> None:
    with _failures_lock:
        _failures.setdefault(client, deque()).append(now)


def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> AdminCredentials:
    configured = admin_credentials()
    if configured is None:
        raise HTTPException(status_code=404)
    client = _client(request)
    now = time.monotonic()
    if _throttled(client, now):
        raise HTTPException(status_code=429, detail="Too many failed sign-ins.")
    if credentials is None or not configured.verify(
        credentials.username, credentials.password
    ):
        if credentials is not None:
            _record_failure(client, now)
            logger.warning("store_admin_auth_failed client=%s", client)
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="PSV store admin"'},
        )
    request.state.admin_csrf_token = configured.csrf_token()
    return configured


def require_csrf(
    admin: AdminCredentials = Depends(require_admin),
    csrf_token: str = Form(""),
) -> None:
    if not hmac.compare_digest(csrf_token.encode(), admin.csrf_token().encode()):
        raise HTTPException(status_code=403, detail="Invalid form token.")


router = APIRouter(
    prefix="/store/admin",
    include_in_schema=False,
    dependencies=[Depends(require_store_enabled), Depends(require_admin)],
)


def _render(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    notice = NOTICES.get(request.query_params.get("notice", ""))
    return templates.TemplateResponse(
        request=request,
        name=f"store/admin/{name}",
        status_code=status_code,
        context={
            "csrf_token": request.state.admin_csrf_token,
            "money": dollars_from_cents,
            "notice": notice,
            **context,
        },
    )


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _int(value: str, label: str) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise db.AdminError(f"{label} must be a whole number.") from None
    if number < 0:
        raise db.AdminError(f"{label} must be zero or greater.")
    return number


def _cents(value: str, label: str) -> int:
    try:
        return cents_from_dollars(value)
    except ValueError:
        raise db.AdminError(f"{label} must be a dollar amount like 12.50.") from None


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    message = str(error.get("msg", "Invalid input."))
    return message.removeprefix("Value error, ")


@router.get("", response_class=HTMLResponse, name="store_admin_dashboard")
def dashboard(request: Request):
    products = db.admin_products()
    return _render(
        request,
        "dashboard.html",
        products=products,
        order_counts=db.admin_order_counts(),
        low_stock=sum(
            1
            for product in products
            if product["published"]
            and any(v["available_stock"] <= 0 for v in product["variants"])
        ),
    )


@router.get(
    "/products/new", response_class=HTMLResponse, name="store_admin_new_product"
)
def new_product_form(request: Request):
    return _render(request, "product_new.html", form={}, error=None)


@router.post(
    "/products",
    dependencies=[Depends(require_csrf)],
    name="store_admin_create_product",
)
def create_product(
    request: Request,
    name: str = Form(""),
    base_sku: str = Form(""),
    category_label: str = Form(""),
    description: str = Form(""),
    variant_name: str = Form(""),
    upc: str = Form(""),
    price: str = Form(""),
    stock: str = Form("0"),
    featured: bool = Form(False),
    published: bool = Form(False),
):
    form = {
        "name": name,
        "base_sku": base_sku,
        "category_label": category_label,
        "description": description,
        "variant_name": variant_name,
        "upc": upc,
        "price": price,
        "stock": stock,
        "featured": featured,
        "published": published,
    }
    try:
        sku = base_sku.strip().upper()
        product = ProductInput(
            name=name,
            slug=sku,
            base_sku=sku,
            description=description.strip(),
            category_label=category_label,
            featured=featured,
            published=published,
            variants=[
                VariantInput(
                    sku=sku,
                    name=variant_name,
                    upc=upc,
                    price_cents=_cents(price, "Price"),
                    stock_on_hand=_int(stock, "Stock"),
                )
            ],
        )
        product_id = db.admin_create_product(product)
    except ValidationError as exc:
        error = _validation_message(exc)
    except db.AdminError as exc:
        error = str(exc)
    else:
        logger.info("store_admin_product_created product_id=%s", product_id)
        return _redirect(
            str(request.url_for("store_admin_product", product_id=product_id))
            + "?notice=created"
        )
    return _render(request, "product_new.html", 400, form=form, error=error)


@router.get(
    "/products/{product_id}",
    response_class=HTMLResponse,
    name="store_admin_product",
)
def product_form(request: Request, product_id: int):
    product = db.admin_product(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return _render(request, "product.html", product=product, error=None)


@router.post(
    "/products/{product_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_update_product",
)
def update_product(
    request: Request,
    product_id: int,
    name: str = Form(""),
    description: str = Form(""),
    featured: bool = Form(False),
    published: bool = Form(False),
    variant_id: list[str] = Form([]),
    variant_name: list[str] = Form([]),
    variant_upc: list[str] = Form([]),
    variant_price: list[str] = Form([]),
    variant_stock: list[str] = Form([]),
    variant_expected_stock: list[str] = Form([]),
):
    try:
        fields = (
            variant_id,
            variant_name,
            variant_upc,
            variant_price,
            variant_stock,
            variant_expected_stock,
        )
        if len({len(values) for values in fields}) != 1:
            raise db.AdminError("The variant fields are incomplete.")
        variants = [
            VariantUpdate(
                id=_int(row_id, "Variant"),
                name=row_name,
                upc=row_upc,
                price_cents=_cents(row_price, "Price"),
                stock_on_hand=_int(row_stock, "Stock"),
                expected_stock=_int(row_expected, "Stock"),
            )
            for row_id, row_name, row_upc, row_price, row_stock, row_expected in zip(
                *fields
            )
        ]
        db.update_product(
            product_id,
            name=name,
            description=description,
            featured=featured,
            published=published,
            variants=variants,
        )
    except ValidationError as exc:
        error = _validation_message(exc)
    except db.AdminError as exc:
        error = str(exc)
    else:
        logger.info("store_admin_product_updated product_id=%s", product_id)
        return _redirect(
            str(request.url_for("store_admin_product", product_id=product_id))
            + "?notice=saved"
        )
    product = db.admin_product(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return _render(request, "product.html", 400, product=product, error=error)


@router.post(
    "/products/{product_id}/variants",
    dependencies=[Depends(require_csrf)],
    name="store_admin_add_variant",
)
def add_variant(
    request: Request,
    product_id: int,
    sku: str = Form(""),
    name: str = Form(""),
    upc: str = Form(""),
    price: str = Form(""),
    stock: str = Form("0"),
):
    try:
        db.add_variant(
            product_id,
            VariantInput(
                sku=sku,
                name=name,
                upc=upc,
                price_cents=_cents(price, "Price"),
                stock_on_hand=_int(stock, "Stock"),
            ),
        )
    except ValidationError as exc:
        error = _validation_message(exc)
    except db.AdminError as exc:
        error = str(exc)
    else:
        logger.info("store_admin_variant_added product_id=%s", product_id)
        return _redirect(
            str(request.url_for("store_admin_product", product_id=product_id))
            + "?notice=variant"
        )
    product = db.admin_product(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return _render(request, "product.html", 400, product=product, error=error)


@router.get("/orders", response_class=HTMLResponse, name="store_admin_orders")
def orders(request: Request, fulfillment: str = ""):
    if fulfillment not in db.ORDER_FULFILLMENT_STATES:
        fulfillment = ""
    return _render(
        request,
        "orders.html",
        orders=db.admin_orders(fulfillment_state=fulfillment or None),
        fulfillment=fulfillment,
        states=db.ORDER_FULFILLMENT_STATES,
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse, name="store_admin_order")
def order_detail(request: Request, order_id: str):
    order = db.admin_order(order_id)
    if order is None:
        raise HTTPException(status_code=404)
    return _render(request, "order.html", **_order_context(order), error=None)


@router.post(
    "/orders/{order_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_update_order",
)
def update_order(
    request: Request,
    order_id: str,
    fulfillment_state: str = Form(""),
    review_state: str = Form(""),
    review_reason: str = Form(""),
):
    try:
        db.update_order(
            order_id,
            fulfillment_state=fulfillment_state,
            review_state=review_state,
            review_reason=review_reason,
        )
    except db.AdminError as exc:
        order = db.admin_order(order_id)
        if order is None:
            raise HTTPException(status_code=404) from None
        return _render(
            request, "order.html", 400, **_order_context(order), error=str(exc)
        )
    logger.info("store_admin_order_updated order_id=%s", order_id)
    return _redirect(
        str(request.url_for("store_admin_order", order_id=order_id)) + "?notice=saved"
    )


def _order_context(order: dict[str, Any]) -> dict[str, Any]:
    shipping = order.get("shipping_json") or {}
    address = shipping.get("address") if isinstance(shipping, dict) else None
    return {
        "order": order,
        "ship_name": shipping.get("name") if isinstance(shipping, dict) else None,
        "address": address if isinstance(address, dict) else {},
        "fulfillment_states": db.ORDER_FULFILLMENT_STATES,
        "review_states": db.ORDER_REVIEW_STATES,
    }
