from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.responses import JSONResponse

from ..dependencies import templates
from .products import get_all_products, get_categories, get_featured_products, get_product_by_slug
from .stripe import create_checkout_session

router = APIRouter(prefix="/store")


class CartItem(BaseModel):
    slug: str
    quantity: int


class CheckoutRequest(BaseModel):
    items: list[CartItem]


@router.get("", response_class=HTMLResponse)
def store_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/store.html",
        context={
            "products": get_all_products(),
            "categories": get_categories(),
            "featured": get_featured_products(),
        },
    )


@router.get("/cart", response_class=HTMLResponse)
def store_cart_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/store-cart.html")


@router.get("/success", response_class=HTMLResponse)
def store_success_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/store-success.html")


@router.post("/checkout")
async def store_checkout(request: Request, checkout: CheckoutRequest):
    line_items = []
    for item in checkout.items:
        product = get_product_by_slug(item.slug)
        if not product or not product["in_stock"]:
            return JSONResponse(
                status_code=400,
                content={"error": f"Product '{item.slug}' not available"},
            )
        line_items.append(
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": product["name"]},
                    "unit_amount": product["price_cents"],
                },
                "quantity": item.quantity,
            }
        )

    base_url = str(request.base_url).rstrip("/")
    checkout_url = create_checkout_session(
        line_items=line_items,
        success_url=f"{base_url}/store/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/store/cart",
    )
    return JSONResponse(content={"checkout_url": checkout_url})


@router.get("/{slug}", response_class=HTMLResponse)
def store_product_page(request: Request, slug: str):
    product = get_product_by_slug(slug)
    if not product:
        return templates.TemplateResponse(
            request=request, name="404.html", status_code=404
        )
    return templates.TemplateResponse(
        request=request,
        name="pages/store-product.html",
        context={"product": product},
    )
