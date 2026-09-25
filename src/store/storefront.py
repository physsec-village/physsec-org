"""Presentation adapters joining the menu catalog with live inventory.

Copy, photos, and grouping come from `catalog` (the menu). Price and
availability come from PostgreSQL so the storefront never shows a price that
checkout would not charge. Items missing from the database are shown but
cannot be added to a cart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import catalog, db
from .catalog import Collection, StoreGroup, StoreItem

Inventory = dict[str, dict[str, Any]]


def money(cents: int) -> str:
    dollars, remainder = divmod(int(cents), 100)
    return f"${dollars}" if remainder == 0 else f"${dollars}.{remainder:02d}"


@dataclass(frozen=True)
class ItemView:
    item: StoreItem
    price_cents: int
    available_stock: int
    listed: bool

    def __getattr__(self, name: str) -> Any:
        return getattr(self.item, name)

    @property
    def price_str(self) -> str:
        return money(self.price_cents)

    @property
    def purchasable(self) -> bool:
        return self.listed and not self.restricted and self.available_stock > 0

    @property
    def sold_out(self) -> bool:
        return self.listed and not self.restricted and self.available_stock <= 0

    @property
    def image_url(self) -> str:
        return f"/static/images/menu/{self.image}" if self.image else ""

    @property
    def url(self) -> str:
        return f"/store/product/{self.slug}"

    @property
    def collection(self) -> Collection:
        return catalog.collection_for(self.item)


@dataclass(frozen=True)
class GroupView:
    group: StoreGroup
    items: tuple[ItemView, ...]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.group, name)


@dataclass(frozen=True)
class CollectionView:
    collection: Collection
    groups: tuple[GroupView, ...]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.collection, name)

    @property
    def cover_url(self) -> str:
        return f"/static/images/menu/{self.cover}" if self.cover else ""

    @property
    def url(self) -> str:
        return f"/store/collection/{self.slug}"


class Storefront:
    """One request's view of the catalog against a single inventory snapshot."""

    def __init__(self, inventory: Inventory | None = None):
        self.inventory = db.sku_inventory() if inventory is None else inventory

    def view(self, item: StoreItem) -> ItemView:
        row = self.inventory.get(item.sku)
        if row is None:
            return ItemView(item, item.price_cents, 0, listed=False)
        return ItemView(
            item, int(row["price_cents"]), int(row["available_stock"]), listed=True
        )

    def views(self, items: tuple[StoreItem, ...]) -> tuple[ItemView, ...]:
        return tuple(self.view(item) for item in items)

    def collection(self, collection: Collection) -> CollectionView:
        return CollectionView(
            collection,
            tuple(
                GroupView(group, self.views(group.items)) for group in collection.groups
            ),
        )

    def collections(self) -> tuple[CollectionView, ...]:
        return tuple(self.collection(c) for c in catalog.COLLECTIONS)

    def browser_catalog(self) -> dict[str, Any]:
        """SKU-keyed map embedded in store pages for the client-side cart."""
        result: dict[str, Any] = {}
        for item in catalog.ITEMS:
            view = self.view(item)
            if not view.listed or view.restricted:
                continue
            result[item.sku] = {
                "name": item.name,
                "price_cents": view.price_cents,
                "available_stock": view.available_stock,
                "image": view.image_url,
                "url": view.url,
            }
        return result
