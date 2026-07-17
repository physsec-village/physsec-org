import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from ..dependencies import templates
from . import db
from .models import ProductInput, VariantInput, cents_from_dollars, dollars_from_cents

logger = logging.getLogger(__name__)

# SVG is intentionally excluded: served files could run active content when
# opened directly, and the admin has no auth yet.
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def admin_gate() -> None:
    if os.getenv("ADMIN_UNPROTECTED") != "true":
        raise HTTPException(status_code=404)


router = APIRouter(prefix="/admin/store", dependencies=[Depends(admin_gate)])


def warn_if_unprotected_admin() -> None:
    if os.getenv("ADMIN_UNPROTECTED") == "true":
        logger.warning("ADMIN_UNPROTECTED=true — /admin/store has NO authentication")


def cents(value: int) -> str:
    return f"${(value or 0) / 100:.2f}"


def product_price(product: dict[str, Any]) -> str:
    if product.get("min_price_cents") != product.get("max_price_cents"):
        return f"{cents(product['min_price_cents'])}–{cents(product['max_price_cents'])}"
    return cents(product.get("price_cents", 0))


@router.get("", response_class=HTMLResponse, name="admin_store_page")
def admin_store_page(request: Request, saved: int | None = None):
    return templates.TemplateResponse(
        request=request,
        name="admin/store-index.html",
        context={
            "products": db.list_admin_products(),
            "saved": saved,
            "cents": cents,
            "product_price": product_price,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="admin_store_new_page")
def admin_store_new_page(request: Request):
    return _render_form(request, _empty_product(), "New product")


@router.post("/new")
def admin_store_create(
    request: Request,
    name: Annotated[str, Form()],
    base_sku: Annotated[str, Form()],
    variant_prices: Annotated[list[str], Form()],
    variant_stocks: Annotated[list[int], Form()],
    variant_positions: Annotated[list[int], Form()],
    slug: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category_label: Annotated[str, Form()] = "",
    variant_names: Annotated[list[str], Form()] = [],
    variant_suffixes: Annotated[list[str], Form()] = [],
    featured: Annotated[bool, Form()] = False,
    published: Annotated[bool, Form()] = False,
    image_files: Annotated[list[UploadFile], File()] = [],
):
    product_data = _form_product_dict(
        name,
        slug,
        base_sku,
        description,
        category_label,
        featured,
        published,
        variant_names,
        variant_suffixes,
        variant_prices,
        variant_stocks,
        variant_positions,
    )
    images: list[dict[str, Any]] = []
    try:
        _raise_form_errors(product_data)
        product = _product_input(product_data)
        images = _save_uploads(image_files)
        product_id = db.create_product(product, images)
    except (ValueError, ValidationError, sqlite3.IntegrityError) as exc:
        _delete_upload_files(images)
        return _render_form(request, product_data, "New product", _clean_error(exc))
    return RedirectResponse(
        request.url_for("admin_store_edit_page", product_id=product_id).include_query_params(saved=1),
        status_code=303,
    )


@router.get("/orders", response_class=HTMLResponse, name="admin_store_orders_page")
def admin_store_orders_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/store-orders.html",
        context={"orders": db.list_orders(), "cents": cents},
    )


@router.get("/{product_id}/edit", response_class=HTMLResponse, name="admin_store_edit_page")
def admin_store_edit_page(request: Request, product_id: int, saved: int | None = None):
    product = db.get_product_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    return _render_form(request, product, "Edit product", saved=saved)


@router.post("/{product_id}/edit")
def admin_store_update(
    request: Request,
    product_id: int,
    name: Annotated[str, Form()],
    base_sku: Annotated[str, Form()],
    variant_prices: Annotated[list[str], Form()],
    variant_stocks: Annotated[list[int], Form()],
    variant_positions: Annotated[list[int], Form()],
    slug: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category_label: Annotated[str, Form()] = "",
    variant_names: Annotated[list[str], Form()] = [],
    variant_suffixes: Annotated[list[str], Form()] = [],
    image_ids: Annotated[list[int], Form()] = [],
    image_alts: Annotated[list[str], Form()] = [],
    image_positions: Annotated[list[int], Form()] = [],
    delete_image_ids: Annotated[list[int], Form()] = [],
    featured: Annotated[bool, Form()] = False,
    published: Annotated[bool, Form()] = False,
    image_files: Annotated[list[UploadFile], File()] = [],
):
    current = db.get_product_by_id(product_id)
    if current is None:
        raise HTTPException(status_code=404)
    product_data = _form_product_dict(
        name,
        slug,
        base_sku,
        description,
        category_label,
        featured,
        published,
        variant_names,
        variant_suffixes,
        variant_prices,
        variant_stocks,
        variant_positions,
        product_id=product_id,
        images=_form_images(image_ids, image_alts, image_positions, current.get("images", [])),
    )
    images: list[dict[str, Any]] = []
    try:
        _raise_form_errors(product_data)
        product = _product_input(product_data)
        images = _save_uploads(image_files)
        db.update_product(product_id, product, product_data["images"], delete_image_ids, images)
    except (ValueError, ValidationError, sqlite3.IntegrityError) as exc:
        _delete_upload_files(images)
        return _render_form(request, product_data, "Edit product", _clean_error(exc))
    return RedirectResponse(
        request.url_for("admin_store_edit_page", product_id=product_id).include_query_params(saved=1),
        status_code=303,
    )


@router.post("/{product_id}/toggle/{flag}")
def admin_store_toggle(request: Request, product_id: int, flag: str):
    product = db.get_product_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404)
    if flag not in {"featured", "published"}:
        raise HTTPException(status_code=404)
    db.set_product_flag(product_id, flag, not bool(product[flag]))
    return RedirectResponse(request.url_for("admin_store_page").include_query_params(saved=1), status_code=303)


@router.post("/{product_id}/delete")
def admin_store_delete(request: Request, product_id: int):
    db.delete_product(product_id)
    return RedirectResponse(request.url_for("admin_store_page").include_query_params(saved=1), status_code=303)


def _render_form(
    request: Request,
    product: dict[str, Any],
    title: str,
    error: str | None = None,
    saved: int | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="admin/store-form.html",
        context={
            "product": _normalize_for_form(product),
            "title": title,
            "error": error,
            "saved": saved,
            "dollars_from_cents": dollars_from_cents,
        },
    )


def _empty_product() -> dict[str, Any]:
    return {
        "id": None,
        "name": "",
        "slug": "",
        "base_sku": "",
        "description": "",
        "category_label": "",
        "featured": 0,
        "published": 1,
        "variants": [{"name": "", "sku": "", "suffix": "", "price_cents": 0, "stock": 0, "position": 0}],
        "images": [],
    }


def _normalize_for_form(product: dict[str, Any]) -> dict[str, Any]:
    product = dict(product)
    base_sku = product.get("base_sku") or ""
    variants = []
    for variant in product.get("variants", []):
        variant = dict(variant)
        sku = variant.get("sku", "")
        suffix = ""
        if base_sku and sku.startswith(f"{base_sku}-"):
            suffix = sku.removeprefix(f"{base_sku}-")
        variant["suffix"] = variant.get("suffix", suffix)
        variants.append(variant)
    product["variants"] = variants or _empty_product()["variants"]
    product["images"] = list(product.get("images", []))
    return product


def _form_product_dict(
    name: str,
    slug: str,
    base_sku: str,
    description: str,
    category_label: str,
    featured: bool,
    published: bool,
    variant_names: list[str],
    variant_suffixes: list[str],
    variant_prices: list[str],
    variant_stocks: list[int],
    variant_positions: list[int],
    product_id: int | None = None,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base_sku = base_sku.strip().upper()
    variants = []
    errors = []
    count = max(len(variant_names), len(variant_suffixes), len(variant_prices), len(variant_stocks), len(variant_positions))
    for index in range(count):
        suffix = _at(variant_suffixes, index).strip()
        sku = base_sku if not suffix else f"{base_sku}-{suffix}"
        # Collect price errors instead of raising so the form can re-render
        # with an error message rather than a 500.
        try:
            price_cents = cents_from_dollars(_at(variant_prices, index) or "0")
        except ValueError as exc:
            price_cents = 0
            errors.append(str(exc))
        variants.append(
            {
                "name": _at(variant_names, index).strip(),
                "sku": sku,
                "suffix": suffix,
                "price_cents": price_cents,
                "stock": int(_at(variant_stocks, index) or 0),
                "position": int(_at(variant_positions, index) or index),
            }
        )
    return {
        "errors": errors,
        "id": product_id,
        "name": name,
        "slug": slug,
        "base_sku": base_sku,
        "description": description,
        "category_label": category_label,
        "featured": int(featured),
        "published": int(published),
        "variants": variants,
        "images": images or [],
    }


def _raise_form_errors(product_data: dict[str, Any]) -> None:
    errors = product_data.get("errors") or []
    if errors:
        raise ValueError(errors[0])


def _product_input(product_data: dict[str, Any]) -> ProductInput:
    return ProductInput(
        name=product_data["name"],
        slug=product_data["slug"],
        base_sku=product_data["base_sku"],
        description=product_data["description"],
        category_label=product_data["category_label"],
        featured=bool(product_data["featured"]),
        published=bool(product_data["published"]),
        variants=[VariantInput(**variant) for variant in product_data["variants"]],
    )


def _form_images(
    ids: list[int],
    alts: list[str],
    positions: list[int],
    current_images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_id = {int(image["id"]): image for image in current_images or []}
    images = []
    for index, image_id in enumerate(ids):
        current = by_id.get(int(image_id), {})
        images.append(
            {
                "id": int(image_id),
                "alt": _at(alts, index),
                "position": int(_at(positions, index) or index),
                "filename": current.get("filename", ""),
                "url": current.get("url", ""),
            }
        )
    return images


def _image_signature_matches(ext: str, data: bytes) -> bool:
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def _save_uploads(files: list[UploadFile]) -> list[dict[str, Any]]:
    images = []
    try:
        for position, upload in enumerate(files or []):
            if not upload or not upload.filename:
                continue
            ext = Path(upload.filename).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValueError("Images must be png, jpg, jpeg, or webp files.")
            data = upload.file.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("Images must be 10 MB or smaller.")
            if not _image_signature_matches(ext, data):
                raise ValueError("Image content does not match its file extension.")
            filename = f"{uuid.uuid4().hex}{ext}"
            (db.MEDIA_DIR / filename).write_bytes(data)
            images.append({"filename": filename, "alt": "", "position": position})
    except ValueError:
        _delete_upload_files(images)
        raise
    return images


def _delete_upload_files(images: list[dict[str, Any]]) -> None:
    for image in images or []:
        if image.get("filename"):
            (db.MEDIA_DIR / image["filename"]).unlink(missing_ok=True)


def _at(values: list[Any], index: int) -> Any:
    if index >= len(values):
        return ""
    return values[index]


def _clean_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors())
    if isinstance(exc, sqlite3.IntegrityError):
        return "A product or variant with that slug or SKU already exists."
    return str(exc)
