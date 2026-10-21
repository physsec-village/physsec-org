"""Basic store administration UI: products, variants, stock, and orders.

The UI is hidden (404) while the store is disabled. Sign-in is a placeholder
with hardcoded credentials; see admin_auth. Every form also carries a CSRF
token.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from ..dependencies import templates
from . import admin_auth, db
from .models import (
    ProductInput,
    VariantInput,
    VariantUpdate,
    cents_from_dollars,
    dollars_from_cents,
)
from .router import require_store_enabled

logger = logging.getLogger(__name__)

NOTICES = {
    "saved": "Changes saved.",
    "created": "Product created.",
    "variant": "Variant added.",
    "signed_out": "Signed out.",
}


def require_admin(request: Request) -> None:
    if not admin_auth.valid_session(request.cookies.get(admin_auth.SESSION_COOKIE)):
        raise HTTPException(
            status_code=303,
            headers={"Location": str(request.url_for("store_admin_login"))},
        )


def require_csrf(csrf_token: str = Form("")) -> None:
    if not admin_auth.valid_csrf(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid form token.")


# Sign-in pages, reachable without a session.
public_router = APIRouter(
    prefix="/store/admin",
    include_in_schema=False,
    dependencies=[Depends(require_store_enabled)],
)

router = APIRouter(
    prefix="/store/admin",
    include_in_schema=False,
    dependencies=[Depends(require_store_enabled), Depends(require_admin)],
)


@public_router.get("/login", response_class=HTMLResponse, name="store_admin_login")
def login_form(request: Request):
    return _render(request, "login.html", error=None)


@public_router.post(
    "/login",
    dependencies=[Depends(require_csrf)],
    name="store_admin_login_submit",
)
def login(request: Request, username: str = Form(""), password: str = Form("")):
    if not admin_auth.check_credentials(username, password):
        return _render(request, "login.html", 401, error="Wrong username or password.")
    response = _redirect(str(request.url_for("store_admin_dashboard")))
    response.set_cookie(
        admin_auth.SESSION_COOKIE,
        admin_auth.session_token(),
        path="/store/admin",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@public_router.post(
    "/logout",
    dependencies=[Depends(require_csrf)],
    name="store_admin_logout",
)
def logout(request: Request):
    response = _redirect(
        str(request.url_for("store_admin_login")) + "?notice=signed_out"
    )
    response.delete_cookie(admin_auth.SESSION_COOKIE, path="/store/admin")
    return response


def _render(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    notice = NOTICES.get(request.query_params.get("notice", ""))
    return templates.TemplateResponse(
        request=request,
        name=f"store/admin/{name}",
        status_code=status_code,
        context={
            "csrf_token": admin_auth.csrf_token(),
            "money": dollars_from_cents,
            "notice": notice,
            "signed_in": admin_auth.valid_session(
                request.cookies.get(admin_auth.SESSION_COOKIE)
            ),
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


def _features(value: str) -> list[str]:
    return value.splitlines()


def _group_ids(values: list[str]) -> list[int]:
    try:
        return [int(value) for value in values]
    except ValueError:
        raise db.AdminError("A selected collection is not valid.") from None


@router.get(
    "/products/new", response_class=HTMLResponse, name="store_admin_new_product"
)
def new_product_form(request: Request):
    return _render(
        request,
        "product_new.html",
        form={"group_ids": set()},
        groups=db.admin_collection_groups(),
        error=None,
    )


@router.post(
    "/products",
    dependencies=[Depends(require_csrf)],
    name="store_admin_create_product",
)
def create_product(
    request: Request,
    name: str = Form(""),
    slug: str = Form(""),
    description: str = Form(""),
    features: str = Form(""),
    group_id: list[str] = Form([]),
    variant_name: str = Form(""),
    sku: str = Form(""),
    upc: str = Form(""),
    price: str = Form(""),
    stock: str = Form("0"),
    featured: bool = Form(False),
    published: bool = Form(False),
):
    form = {
        "name": name,
        "slug": slug,
        "description": description,
        "features": features,
        "group_ids": {int(value) for value in group_id if value.isdigit()},
        "variant_name": variant_name,
        "sku": sku,
        "upc": upc,
        "price": price,
        "stock": stock,
        "featured": featured,
        "published": published,
    }
    try:
        product = ProductInput(
            name=name,
            slug=slug,
            description=description,
            features=_features(features),
            featured=featured,
            published=published,
            group_ids=_group_ids(group_id),
        )
        variant = VariantInput(
            name=variant_name,
            sku=sku,
            upc=upc,
            price_cents=_cents(price, "Price"),
            stock_on_hand=_int(stock, "Stock"),
        )
        product_id = db.admin_create_product(product, variant)
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
    return _render(
        request,
        "product_new.html",
        400,
        form=form,
        groups=db.admin_collection_groups(),
        error=error,
    )


def _product_page(
    request: Request, product_id: int, status_code: int = 200, error: str | None = None
) -> HTMLResponse:
    product = db.admin_product(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return _render(
        request,
        "product.html",
        status_code,
        product=product,
        groups=db.admin_collection_groups(),
        error=error,
    )


@router.get(
    "/products/{product_id}",
    response_class=HTMLResponse,
    name="store_admin_product",
)
def product_form(request: Request, product_id: int):
    return _product_page(request, product_id)


@router.post(
    "/products/{product_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_update_product",
)
def update_product(
    request: Request,
    product_id: int,
    name: str = Form(""),
    slug: str = Form(""),
    description: str = Form(""),
    features: str = Form(""),
    group_id: list[str] = Form([]),
    featured: bool = Form(False),
    published: bool = Form(False),
    version: str = Form(""),
    variant_id: list[str] = Form([]),
    variant_name: list[str] = Form([]),
    variant_sku: list[str] = Form([]),
    variant_upc: list[str] = Form([]),
    variant_price: list[str] = Form([]),
    variant_stock: list[str] = Form([]),
    variant_expected_stock: list[str] = Form([]),
):
    try:
        fields = (
            variant_id,
            variant_name,
            variant_sku,
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
                sku=row_sku,
                upc=row_upc,
                price_cents=_cents(row_price, "Price"),
                stock_on_hand=_int(row_stock, "Stock"),
                expected_stock=_int(row_expected, "Stock"),
            )
            for (
                row_id,
                row_name,
                row_sku,
                row_upc,
                row_price,
                row_stock,
                row_expected,
            ) in zip(*fields)
        ]
        product = ProductInput(
            name=name,
            slug=slug,
            description=description,
            features=_features(features),
            featured=featured,
            published=published,
            group_ids=_group_ids(group_id),
        )
        db.update_product(product_id, product, variants=variants, version=version)
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
    return _product_page(request, product_id, 400, error)


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
    return _product_page(request, product_id, 400, error)


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
    version: str = Form(""),
):
    try:
        db.update_order(
            order_id,
            fulfillment_state=fulfillment_state,
            review_state=review_state,
            review_reason=review_reason,
            version=version,
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
