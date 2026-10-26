"""Store administration UI: the catalog, orders and the Stripe webhook ledger.

The whole catalog is edited here: products with their variants and images,
and collections with their groups and the products in them. Payments live in
the Stripe dashboard; the admin links to it and shows what Stripe's webhooks
have told the store.

The UI is hidden (404) while the store is disabled. Sign-in is handled by
Clerk (see admin_auth): the login page mounts Clerk's sign-in component, and
every other page requires a verified Clerk session whose token carries
``admin: true`` from the user's public metadata. Every form also carries a CSRF
token bound to that session.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from ..dependencies import templates
from . import admin_auth, config, db, media, stripe_client
from .models import (
    CollectionInput,
    GroupInput,
    GroupUpdate,
    ImageUpdate,
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
    "reviewed": "Marked as reviewed.",
    "created": "Product created.",
    "variant": "Variant added.",
    "image": "Image added.",
    "moved": "Order updated.",
    "deleted": "Deleted.",
    "collection_created": "Collection created.",
    "group": "Group added.",
    "item": "Product added to the group.",
    "signed_out": "Signed out.",
}
PRODUCT_FILTERS = {
    "": "All products",
    "published": "Published",
    "hidden": "Hidden",
    "featured": "Featured",
    "sold_out": "Published with a sold-out variant",
    "unlisted": "Not in any collection",
    "unreviewed": "Not yet reviewed",
}
REVIEW_PATH = "/store/admin/review"


class NotAnAdmin(Exception):
    """Raised for a signed-in Clerk user whose public metadata lacks admin."""


def current_session(request: Request) -> admin_auth.Session | None:
    """Verify the request's Clerk session once and remember it."""
    if not hasattr(request.state, "admin_session"):
        request.state.admin_session = admin_auth.session_from_request(request)
    return request.state.admin_session


def require_admin(request: Request) -> admin_auth.Session:
    session = current_session(request)
    if session is None:
        raise HTTPException(
            status_code=303,
            headers={"Location": str(request.url_for("store_admin_login"))},
        )
    if not session.admin:
        logger.warning("store_admin_forbidden user_id=%s", session.user_id)
        raise NotAnAdmin
    request.state.admin = True
    return session


def require_csrf(request: Request, csrf_token: str = Form("")) -> None:
    session = current_session(request)
    if session is None or not admin_auth.valid_csrf(session, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid form token.")


async def not_an_admin(request: Request, exc: NotAnAdmin) -> Response:
    """Render the 403 page offering sign-out to a non-admin Clerk user."""
    return _render(request, "forbidden.html", 403)


# Sign-in page, reachable without a session.
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
    if current_session(request) is not None:
        return _redirect(str(request.url_for("store_admin_dashboard")))
    return _render(request, "login.html", error=None)


def _render(
    request: Request, name: str, status_code: int = 200, **context: Any
) -> HTMLResponse:
    notice = NOTICES.get(request.query_params.get("notice", ""))
    session = current_session(request)
    return templates.TemplateResponse(
        request=request,
        name=f"store/admin/{name}",
        status_code=status_code,
        context={
            "csrf_token": admin_auth.csrf_token(session) if session else "",
            "money": dollars_from_cents,
            "notice": notice,
            "signed_in": session is not None,
            "admin": getattr(request.state, "admin", False),
            "stripe_url": stripe_client.dashboard_url,
            "clerk": {
                "publishable_key": config.clerk_publishable_key(),
                "frontend_api": config.clerk_frontend_api(),
            },
            **context,
        },
    )


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _back(
    request: Request, route: str, notice: str, next_url: str = "", **params: Any
) -> RedirectResponse:
    """Redirect after an action, back to the review page when it came from there."""
    if next_url.startswith(REVIEW_PATH) and "\n" not in next_url:
        return _redirect(next_url)
    return _redirect(str(request.url_for(route, **params)) + f"?notice={notice}")


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


def _message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return _validation_message(exc)
    return str(exc)


def _features(value: str) -> list[str]:
    return value.splitlines()


def _group_ids(values: list[str]) -> list[int]:
    try:
        return [int(value) for value in values]
    except ValueError:
        raise db.AdminError("A selected collection is not valid.") from None


def _rows(*fields: list[str], label: str) -> list[tuple[str, ...]]:
    """Zip parallel form lists, rejecting a form missing some of a row."""
    if len({len(values) for values in fields}) != 1:
        raise db.AdminError(f"The {label} fields are incomplete.")
    return list(zip(*fields, strict=True))


# Products.
def _matches(product: dict[str, Any], needle: str) -> bool:
    if needle in product["name"].lower() or needle in product["slug"]:
        return True
    return any(
        needle in (variant["sku"] or "").lower() or needle in variant["name"].lower()
        for variant in product["variants"]
    )


def _has_sold_out_variant(product: dict[str, Any]) -> bool:
    return any(
        v["published"] and v["available_stock"] <= 0 for v in product["variants"]
    )


def filter_products(
    products: list[dict[str, Any]], query: str, status: str
) -> list[dict[str, Any]]:
    needle = " ".join(query.split()).lower()
    if needle:
        products = [p for p in products if _matches(p, needle)]
    if status == "published":
        return [p for p in products if p["published"]]
    if status == "hidden":
        return [p for p in products if not p["published"]]
    if status == "featured":
        return [p for p in products if p["featured"]]
    if status == "sold_out":
        return [p for p in products if p["published"] and _has_sold_out_variant(p)]
    if status == "unlisted":
        return [p for p in products if not p["groups"]]
    if status == "unreviewed":
        return [p for p in products if p["reviewed_at"] is None]
    return products


@router.get("", response_class=HTMLResponse, name="store_admin_dashboard")
def dashboard(request: Request, q: str = "", status: str = ""):
    if status not in PRODUCT_FILTERS:
        status = ""
    q = q[:80]
    products = db.admin_products()
    return _render(
        request,
        "dashboard.html",
        products=filter_products(products, q, status),
        total=len(products),
        published_count=sum(1 for product in products if product["published"]),
        unreviewed_count=sum(1 for p in products if p["reviewed_at"] is None),
        query=q,
        status=status,
        filters=PRODUCT_FILTERS,
        order_counts=db.admin_order_counts(),
        review_count=db.admin_review_count(),
        low_stock=sum(
            1 for product in products
            if product["published"] and _has_sold_out_variant(product)
        ),
    )


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
    except (ValidationError, db.AdminError) as exc:
        return _render(
            request,
            "product_new.html",
            400,
            form=form,
            groups=db.admin_collection_groups(),
            error=_message(exc),
        )
    logger.info("store_admin_product_created product_id=%s", product_id)
    return _back(request, "store_admin_product", "created", product_id=product_id)


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


def product_form(
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
    # Checkboxes: only the IDs of variants left published are submitted.
    variant_published: list[str] = Form([]),
    image_id: list[str] = Form([]),
    image_alt: list[str] = Form([]),
) -> dict[str, Any]:
    """Collect the product editor's fields; they are validated when saved."""
    return {
        "name": name,
        "slug": slug,
        "description": description,
        "features": features,
        "group_id": group_id,
        "featured": featured,
        "published": published,
        "version": version,
        "variants": (
            variant_id,
            variant_name,
            variant_sku,
            variant_upc,
            variant_price,
            variant_stock,
            variant_expected_stock,
        ),
        "variant_published": variant_published,
        "images": (image_id, image_alt),
    }


def _save_product(product_id: int, form: dict[str, Any], *, reviewed: bool | None) -> None:
    """Validate and store an editor submission; raises on rejected input."""
    variants = [
        VariantUpdate(
            id=_int(row_id, "Variant"),
            name=row_name,
            sku=row_sku,
            upc=row_upc,
            price_cents=_cents(row_price, "Price"),
            stock_on_hand=_int(row_stock, "Stock"),
            expected_stock=_int(row_expected, "Stock"),
            published=row_id in form["variant_published"],
        )
        for (
            row_id,
            row_name,
            row_sku,
            row_upc,
            row_price,
            row_stock,
            row_expected,
        ) in _rows(*form["variants"], label="variant")
    ]
    images = [
        ImageUpdate(id=_int(row_id, "Image"), alt=row_alt)
        for row_id, row_alt in _rows(*form["images"], label="image")
    ]
    product = ProductInput(
        name=form["name"],
        slug=form["slug"],
        description=form["description"],
        features=_features(form["features"]),
        featured=form["featured"],
        published=form["published"],
        group_ids=_group_ids(form["group_id"]),
    )
    db.update_product(
        product_id,
        product,
        variants=variants,
        version=form["version"],
        images=images,
        reviewed=reviewed,
    )


@router.post(
    "/products/{product_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_update_product",
)
def update_product(
    request: Request,
    product_id: int,
    form: dict[str, Any] = Depends(product_form),
    reviewed: bool = Form(False),
):
    try:
        _save_product(product_id, form, reviewed=reviewed)
    except (ValidationError, db.AdminError) as exc:
        return _product_page(request, product_id, 400, _message(exc))
    logger.info("store_admin_product_updated product_id=%s", product_id)
    return _back(request, "store_admin_product", "saved", product_id=product_id)


@router.post(
    "/products/{product_id}/delete",
    dependencies=[Depends(require_csrf)],
    name="store_admin_delete_product",
)
def delete_product(request: Request, product_id: int):
    try:
        orphaned = db.delete_product(product_id)
    except db.AdminError as exc:
        return _product_page(request, product_id, 400, str(exc))
    for url in orphaned:
        media.remove_image(url)
    logger.info("store_admin_product_deleted product_id=%s", product_id)
    return _back(request, "store_admin_dashboard", "deleted")


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
    next_url: str = Form("", alias="next"),
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
    except (ValidationError, db.AdminError) as exc:
        return _product_page(request, product_id, 400, _message(exc))
    logger.info("store_admin_variant_added product_id=%s", product_id)
    return _back(request, "store_admin_product", "variant", next_url, product_id=product_id)


@router.post(
    "/products/{product_id}/variants/{variant_id}/move",
    dependencies=[Depends(require_csrf)],
    name="store_admin_move_variant",
)
def move_variant(
    request: Request,
    product_id: int,
    variant_id: int,
    direction: str = Form(""),
    next_url: str = Form("", alias="next"),
):
    try:
        db.move_variant(product_id, variant_id, direction)
    except db.AdminError as exc:
        return _product_page(request, product_id, 400, str(exc))
    return _back(request, "store_admin_product", "moved", next_url, product_id=product_id)


@router.post(
    "/products/{product_id}/variants/{variant_id}/delete",
    dependencies=[Depends(require_csrf)],
    name="store_admin_delete_variant",
)
def delete_variant(
    request: Request,
    product_id: int,
    variant_id: int,
    next_url: str = Form("", alias="next"),
):
    try:
        db.delete_variant(product_id, variant_id)
    except db.AdminError as exc:
        return _product_page(request, product_id, 400, str(exc))
    logger.info(
        "store_admin_variant_deleted product_id=%s variant_id=%s", product_id, variant_id
    )
    return _back(request, "store_admin_product", "deleted", next_url, product_id=product_id)


@router.post(
    "/products/{product_id}/images",
    dependencies=[Depends(require_csrf)],
    name="store_admin_add_image",
)
def add_image(
    request: Request,
    product_id: int,
    image: UploadFile | None = File(None),
    url: str = Form(""),
    alt: str = Form(""),
    next_url: str = Form("", alias="next"),
):
    location = ""
    try:
        if image is not None and image.filename:
            location = media.save_image(image.file.read(media.MAX_IMAGE_BYTES + 1))
        else:
            location = media.image_url(url)
        db.add_image(product_id, location, " ".join(alt.split())[:300])
    except (media.MediaError, db.AdminError) as exc:
        if location:
            media.remove_image(location)
        return _product_page(request, product_id, 400, str(exc))
    logger.info("store_admin_image_added product_id=%s", product_id)
    return _back(request, "store_admin_product", "image", next_url, product_id=product_id)


@router.post(
    "/products/{product_id}/images/{image_id}/move",
    dependencies=[Depends(require_csrf)],
    name="store_admin_move_image",
)
def move_image(
    request: Request,
    product_id: int,
    image_id: int,
    direction: str = Form(""),
    next_url: str = Form("", alias="next"),
):
    try:
        db.move_image(product_id, image_id, direction)
    except db.AdminError as exc:
        return _product_page(request, product_id, 400, str(exc))
    return _back(request, "store_admin_product", "moved", next_url, product_id=product_id)


@router.post(
    "/products/{product_id}/images/{image_id}/delete",
    dependencies=[Depends(require_csrf)],
    name="store_admin_delete_image",
)
def delete_image(
    request: Request,
    product_id: int,
    image_id: int,
    next_url: str = Form("", alias="next"),
):
    try:
        orphaned = db.delete_image(product_id, image_id)
    except db.AdminError as exc:
        return _product_page(request, product_id, 400, str(exc))
    if orphaned:
        media.remove_image(orphaned)
    return _back(request, "store_admin_product", "deleted", next_url, product_id=product_id)


# Review queue: go through the unreviewed products one at a time before go-live.
def _review_page(
    request: Request,
    *,
    after: int | None = None,
    product_id: int | None = None,
    status_code: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    queue = db.review_queue(after)
    if product_id is not None:
        queue["product"] = db.admin_product(product_id)
        if queue["product"] is None:
            raise HTTPException(status_code=404)
    return _render(
        request,
        "review.html",
        status_code,
        queue=queue,
        product=queue["product"],
        groups=db.admin_collection_groups(),
        next_url=REVIEW_PATH,
        review_mode=True,
        error=error,
    )


@router.get("/review", response_class=HTMLResponse, name="store_admin_review")
def review(request: Request, after: int | None = None):
    return _review_page(request, after=after)


@router.post(
    "/review/{product_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_review_save",
)
def review_save(
    request: Request,
    product_id: int,
    form: dict[str, Any] = Depends(product_form),
):
    try:
        _save_product(product_id, form, reviewed=True)
    except (ValidationError, db.AdminError) as exc:
        return _review_page(
            request, product_id=product_id, status_code=400, error=_message(exc)
        )
    logger.info("store_admin_product_reviewed product_id=%s", product_id)
    return _redirect(f"{REVIEW_PATH}?after={product_id}&notice=reviewed")


# Collections.
@router.get("/collections", response_class=HTMLResponse, name="store_admin_collections")
def collections(request: Request):
    return _render(
        request,
        "collections.html",
        collections=db.admin_collections(),
        form={},
        error=None,
    )


@router.post(
    "/collections",
    dependencies=[Depends(require_csrf)],
    name="store_admin_create_collection",
)
def create_collection(
    request: Request,
    title: str = Form(""),
    slug: str = Form(""),
    tag: str = Form(""),
    blurb: str = Form(""),
    published: bool = Form(False),
):
    try:
        collection_id = db.create_collection(
            CollectionInput(
                title=title, slug=slug, tag=tag, blurb=blurb, published=published
            )
        )
    except (ValidationError, db.AdminError) as exc:
        return _render(
            request,
            "collections.html",
            400,
            collections=db.admin_collections(),
            form={"title": title, "slug": slug, "tag": tag, "blurb": blurb,
                  "published": published},
            error=_message(exc),
        )
    logger.info("store_admin_collection_created collection_id=%s", collection_id)
    return _back(
        request, "store_admin_collection", "collection_created",
        collection_id=collection_id,
    )


@router.post(
    "/collections/{collection_id}/move",
    dependencies=[Depends(require_csrf)],
    name="store_admin_move_collection",
)
def move_collection(request: Request, collection_id: int, direction: str = Form("")):
    try:
        db.move_collection(collection_id, direction)
    except db.AdminError as exc:
        return _render(
            request, "collections.html", 400,
            collections=db.admin_collections(), form={}, error=str(exc),
        )
    return _back(request, "store_admin_collections", "moved")


def _collection_page(
    request: Request,
    collection_id: int,
    status_code: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    collection = db.admin_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404)
    return _render(
        request,
        "collection.html",
        status_code,
        collection=collection,
        products=db.admin_product_options(),
        error=error,
    )


@router.get(
    "/collections/{collection_id}",
    response_class=HTMLResponse,
    name="store_admin_collection",
)
def collection_form(request: Request, collection_id: int):
    return _collection_page(request, collection_id)


@router.post(
    "/collections/{collection_id}",
    dependencies=[Depends(require_csrf)],
    name="store_admin_update_collection",
)
def update_collection(
    request: Request,
    collection_id: int,
    title: str = Form(""),
    slug: str = Form(""),
    tag: str = Form(""),
    blurb: str = Form(""),
    description: str = Form(""),
    published: bool = Form(False),
    version: str = Form(""),
    group_row_id: list[str] = Form([]),
    group_title: list[str] = Form([]),
    group_tag: list[str] = Form([]),
    group_lede: list[str] = Form([]),
):
    try:
        groups = [
            GroupUpdate(id=_int(row_id, "Group"), title=row_title, tag=row_tag, lede=row_lede)
            for row_id, row_title, row_tag, row_lede in _rows(
                group_row_id, group_title, group_tag, group_lede, label="group"
            )
        ]
        collection = CollectionInput(
            title=title,
            slug=slug,
            tag=tag,
            blurb=blurb,
            description=description,
            published=published,
        )
        db.update_collection(collection_id, collection, groups=groups, version=version)
    except (ValidationError, db.AdminError) as exc:
        return _collection_page(request, collection_id, 400, _message(exc))
    logger.info("store_admin_collection_updated collection_id=%s", collection_id)
    return _back(request, "store_admin_collection", "saved", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/delete",
    dependencies=[Depends(require_csrf)],
    name="store_admin_delete_collection",
)
def delete_collection(request: Request, collection_id: int):
    try:
        db.delete_collection(collection_id)
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    logger.info("store_admin_collection_deleted collection_id=%s", collection_id)
    return _back(request, "store_admin_collections", "deleted")


@router.post(
    "/collections/{collection_id}/groups",
    dependencies=[Depends(require_csrf)],
    name="store_admin_add_group",
)
def add_group(
    request: Request,
    collection_id: int,
    title: str = Form(""),
    tag: str = Form(""),
    lede: str = Form(""),
):
    try:
        db.add_group(collection_id, GroupInput(title=title, tag=tag, lede=lede))
    except (ValidationError, db.AdminError) as exc:
        return _collection_page(request, collection_id, 400, _message(exc))
    return _back(request, "store_admin_collection", "group", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/groups/{group_id}/move",
    dependencies=[Depends(require_csrf)],
    name="store_admin_move_group",
)
def move_group(
    request: Request, collection_id: int, group_id: int, direction: str = Form("")
):
    try:
        db.move_group(collection_id, group_id, direction)
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    return _back(request, "store_admin_collection", "moved", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/groups/{group_id}/delete",
    dependencies=[Depends(require_csrf)],
    name="store_admin_delete_group",
)
def delete_group(request: Request, collection_id: int, group_id: int):
    try:
        db.delete_group(collection_id, group_id)
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    return _back(request, "store_admin_collection", "deleted", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/groups/{group_id}/items",
    dependencies=[Depends(require_csrf)],
    name="store_admin_add_item",
)
def add_item(
    request: Request, collection_id: int, group_id: int, product_id: str = Form("")
):
    try:
        db.add_collection_item(collection_id, group_id, _int(product_id, "Product"))
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    return _back(request, "store_admin_collection", "item", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/groups/{group_id}/items/{product_id}/move",
    dependencies=[Depends(require_csrf)],
    name="store_admin_move_item",
)
def move_item(
    request: Request,
    collection_id: int,
    group_id: int,
    product_id: int,
    direction: str = Form(""),
):
    try:
        db.move_collection_item(collection_id, group_id, product_id, direction)
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    return _back(request, "store_admin_collection", "moved", collection_id=collection_id)


@router.post(
    "/collections/{collection_id}/groups/{group_id}/items/{product_id}/remove",
    dependencies=[Depends(require_csrf)],
    name="store_admin_remove_item",
)
def remove_item(request: Request, collection_id: int, group_id: int, product_id: int):
    try:
        db.remove_collection_item(collection_id, group_id, product_id)
    except db.AdminError as exc:
        return _collection_page(request, collection_id, 400, str(exc))
    return _back(request, "store_admin_collection", "saved", collection_id=collection_id)


# Orders.
@router.get("/orders", response_class=HTMLResponse, name="store_admin_orders")
def orders(request: Request, fulfillment: str = "", review: str = ""):
    if fulfillment not in db.ORDER_FULFILLMENT_STATES:
        fulfillment = ""
    if review not in db.ORDER_REVIEW_STATES:
        review = ""
    return _render(
        request,
        "orders.html",
        orders=db.admin_orders(
            fulfillment_state=fulfillment or None, review_state=review or None
        ),
        fulfillment=fulfillment,
        review=review,
        states=db.ORDER_FULFILLMENT_STATES,
        review_states=db.ORDER_REVIEW_STATES,
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
    return _back(request, "store_admin_order", "saved", order_id=order_id)


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


# Stripe: payments are managed in the Stripe dashboard; this page shows what
# its webhooks have delivered and how the integration is configured.
@router.get("/stripe", response_class=HTMLResponse, name="store_admin_stripe")
def stripe_page(request: Request):
    return _render(
        request,
        "stripe.html",
        config=stripe_client.configuration_status(),
        summary=db.admin_stripe_summary(),
        events=db.admin_stripe_events(),
    )
