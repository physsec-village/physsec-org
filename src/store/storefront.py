"""Presentation adapters for the redesigned storefront."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import catalog, db


@dataclass(frozen=True)
class VariantView:
    code: str
    label: str
    sku: str
    upc: str
    price_cents: int
    available_stock: int


@dataclass(frozen=True)
class ProductView:
    id: str
    name: str
    cat: str
    cat_label: str
    sku: str
    upc: str
    desc: str
    featured: bool
    price_cents: int
    price_str: str
    price_varies: bool
    variants: tuple[VariantView, ...]
    available_stock: int

    @property
    def is_key(self) -> bool:
        return self.cat == "KYS"

    @property
    def sold_out(self) -> bool:
        return self.available_stock <= 0

    @property
    def search_text(self) -> str:
        values = [self.name, self.sku, self.cat_label]
        values.extend(variant.label for variant in self.variants)
        values.extend(variant.sku for variant in self.variants)
        return " ".join(values).lower()


def _money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _view(product: dict[str, Any]) -> ProductView:
    raw_variants = product["variants"]
    variants = tuple(
        VariantView(
            code=(
                variant["sku"].removeprefix(f"{product['base_sku']}-")
                if variant["sku"] != product["base_sku"]
                else "_"
            ),
            label=variant["name"],
            sku=variant["sku"],
            upc=variant["upc"],
            price_cents=int(variant["price_cents"]),
            available_stock=max(0, int(variant["available_stock"])),
        )
        for variant in raw_variants
    )
    first = variants[0]
    price_cents = int(product["min_price_cents"])
    price_str = (
        f"From {_money(price_cents)}"
        if product["price_varies"]
        else _money(price_cents)
    )
    return ProductView(
        id=product["slug"].upper(),
        name=product["name"],
        cat=product["category_code"],
        cat_label=product["category_label"],
        sku=first.sku,
        upc=first.upc,
        desc=product["description"],
        featured=bool(product["featured"]),
        price_cents=price_cents,
        price_str=price_str,
        price_varies=bool(product["price_varies"]),
        variants=variants,
        available_stock=sum(variant.available_stock for variant in variants),
    )


def products() -> tuple[ProductView, ...]:
    return tuple(_view(product) for product in db.get_published_products())


def featured_products(all_products: tuple[ProductView, ...]) -> tuple[ProductView, ...]:
    return tuple(product for product in all_products if product.featured)


def get_product(product_id: str) -> ProductView | None:
    product = db.get_product_by_slug(product_id.lower())
    if product is None:
        product = db.get_product_by_id(product_id)
    return _view(product) if product else None


def related_products(
    product: ProductView, all_products: tuple[ProductView, ...], limit: int = 4
) -> tuple[ProductView, ...]:
    return tuple(
        candidate
        for candidate in all_products
        if candidate.cat == product.cat and candidate.id != product.id
    )[:limit]


def category_hub(all_products: tuple[ProductView, ...]) -> list[dict[str, Any]]:
    return [
        {
            "key": code,
            "label": catalog.CATEGORY_LABELS[code],
            "blurb": catalog.CATEGORY_BLURBS[code],
            "count": sum(product.cat == code for product in all_products),
        }
        for code in catalog.CATEGORY_ORDER
    ]


def browser_catalog(all_products: tuple[ProductView, ...]) -> dict[str, Any]:
    return {
        product.id: {
            "name": product.name,
            "variants": [
                {
                    "sku": variant.sku,
                    "code": variant.code,
                    "label": variant.label,
                    "price_cents": variant.price_cents,
                    "available_stock": variant.available_stock,
                }
                for variant in product.variants
            ],
        }
        for product in all_products
    }
