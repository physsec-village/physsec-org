"""Presentation views for the database catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db


def money(cents: int) -> str:
    dollars, remainder = divmod(int(cents), 100)
    return f"${dollars}" if remainder == 0 else f"${dollars}.{remainder:02d}"


@dataclass(frozen=True)
class VariantView:
    id: int
    name: str
    sku: str | None
    upc: str | None
    price_cents: int
    available_stock: int

    @property
    def price_str(self) -> str:
        return money(self.price_cents)

    @property
    def sold_out(self) -> bool:
        return self.available_stock <= 0

    @property
    def purchasable(self) -> bool:
        return not self.sold_out


@dataclass(frozen=True)
class ProductView:
    id: int
    slug: str
    name: str
    description: str
    features: tuple[str, ...]
    featured: bool
    variants: tuple[VariantView, ...]
    images: tuple[dict[str, Any], ...]
    memberships: tuple[dict[str, Any], ...]

    @property
    def price_cents(self) -> int:
        return min((variant.price_cents for variant in self.variants), default=0)

    @property
    def price_varies(self) -> bool:
        return len({variant.price_cents for variant in self.variants}) > 1

    @property
    def price_str(self) -> str:
        return ("From " if self.price_varies else "") + money(self.price_cents)

    @property
    def available_stock(self) -> int:
        return sum(variant.available_stock for variant in self.variants)

    @property
    def sold_out(self) -> bool:
        return self.available_stock <= 0

    @property
    def purchasable(self) -> bool:
        return not self.sold_out

    @property
    def default_variant(self) -> VariantView | None:
        return next(
            (variant for variant in self.variants if variant.purchasable),
            self.variants[0] if self.variants else None,
        )

    @property
    def url(self) -> str:
        return f"/store/product/{self.slug}"

    @property
    def image_url(self) -> str:
        return self.images[0]["url"] if self.images else ""


@dataclass(frozen=True)
class GroupView:
    id: int
    title: str
    tag: str
    lede: str
    products: tuple[ProductView, ...]

    @property
    def anchor(self) -> str:
        return f"group-{self.id}"


@dataclass(frozen=True)
class CollectionView:
    id: int
    slug: str
    title: str
    tag: str
    blurb: str
    description: str
    item_count: int
    cover_url: str
    groups: tuple[GroupView, ...]

    @property
    def url(self) -> str:
        return f"/store/collection/{self.slug}"

    @property
    def paragraphs(self) -> tuple[str, ...]:
        return tuple(
            part.strip() for part in self.description.split("\n\n") if part.strip()
        )

    @property
    def titled_groups(self) -> tuple[GroupView, ...]:
        return tuple(group for group in self.groups if group.title)


def product_view(product: dict[str, Any]) -> ProductView:
    return ProductView(
        id=product["id"],
        slug=product["slug"],
        name=product["name"],
        description=product["description"],
        features=tuple(product["features"]),
        featured=product["featured"],
        variants=tuple(
            VariantView(
                id=variant["id"],
                name=variant["name"],
                sku=variant["sku"],
                upc=variant.get("upc"),
                price_cents=int(variant["price_cents"]),
                available_stock=max(0, int(variant["available_stock"])),
            )
            for variant in product["variants"]
        ),
        images=tuple(product["images"]),
        memberships=tuple(product.get("memberships", ())),
    )


def collection_view(collection: dict[str, Any]) -> CollectionView:
    groups = tuple(
        GroupView(
            id=group["id"],
            title=group["title"],
            tag=group["tag"],
            lede=group["lede"],
            products=tuple(product_view(product) for product in group["products"]),
        )
        for group in collection.get("groups", ())
    )
    return CollectionView(
        id=collection["id"],
        slug=collection["slug"],
        title=collection["title"],
        tag=collection["tag"],
        blurb=collection["blurb"],
        description=collection["description"],
        item_count=collection.get(
            "item_count", len({p.id for g in groups for p in g.products})
        ),
        cover_url=collection.get("cover_url") or "",
        groups=groups,
    )


def products(*, featured: bool | None = None) -> tuple[ProductView, ...]:
    return tuple(
        product_view(product)
        for product in db.get_published_products(featured=featured)
    )


def collections() -> tuple[CollectionView, ...]:
    return tuple(
        collection_view(collection) for collection in db.get_published_collections()
    )


def browser_catalog(all_products: tuple[ProductView, ...]) -> dict[str, Any]:
    return {
        str(variant.id): {
            "name": product.name,
            "variant_name": variant.name,
            "price_cents": variant.price_cents,
            "available_stock": variant.available_stock,
            "image": product.image_url,
            "url": product.url,
        }
        for product in all_products
        for variant in product.variants
    }


def get_product(slug: str) -> ProductView | None:
    product = db.get_product_by_slug(slug)
    return product_view(product) if product else None
