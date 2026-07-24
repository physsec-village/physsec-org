import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..dependencies import templates
from . import catalog

router = APIRouter(prefix="/store")

_ORDER_NUM_RE = re.compile(r"^PSV-\d{6}$")


def _store_context(**extra) -> dict:
    return {"catalog_json": catalog.catalog_json(), **extra}


@router.get("", response_class=HTMLResponse)
def store_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/store/home.html",
        context=_store_context(
            hero=catalog.HERO,
            featured=catalog.FEATURED,
            categories=catalog.category_hub(),
        ),
    )


@router.get("/catalog", response_class=HTMLResponse)
def store_catalog_page(request: Request, cat: str = "All"):
    if cat not in catalog.CATEGORY_LABELS:
        cat = "All"
    return templates.TemplateResponse(
        request=request,
        name="pages/store/catalog.html",
        context=_store_context(
            products=catalog.PRODUCTS,
            categories=catalog.category_hub(),
            initial_cat=cat,
            all_blurb=catalog.ALL_PRODUCTS_BLURB,
        ),
    )


@router.get("/product/{product_id}", response_class=HTMLResponse)
def store_product_page(request: Request, product_id: str):
    product = catalog.PRODUCT_MAP.get(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="pages/store/product.html",
        context=_store_context(
            product=product,
            related=catalog.related_products(product),
        ),
    )


@router.get("/checkout", response_class=HTMLResponse)
def store_checkout_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/store/checkout.html",
        context=_store_context(
            free_shipping_threshold=catalog.FREE_SHIPPING_THRESHOLD,
            flat_shipping=catalog.FLAT_SHIPPING,
        ),
    )


@router.get("/confirmed", response_class=HTMLResponse)
def store_confirmed_page(request: Request, order: str = ""):
    if not _ORDER_NUM_RE.match(order):
        order = f"PSV-{secrets.randbelow(900000) + 100000}"
    return templates.TemplateResponse(
        request=request,
        name="pages/store/confirmed.html",
        context=_store_context(order_num=order),
    )
