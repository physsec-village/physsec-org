"""Resumable import of the menu-derived catalog into PostgreSQL."""

from __future__ import annotations

import logging

from . import catalog, db
from .config import bootstrap_stock
from .models import ProductInput, VariantInput

logger = logging.getLogger(__name__)


def bootstrap_catalog() -> int:
    """Serialize catalog bootstrap across concurrent application starts."""
    with db.catalog_bootstrap_lock():
        return _bootstrap_catalog()


def _bootstrap_catalog() -> int:
    """Import menu items that the database does not know about yet.

    Every menu item becomes one product with one variant keyed by its SKU.
    Prices come from the menu, but stock defaults to zero so a fresh
    production deployment cannot accidentally sell unconfigured items.
    Items that require vetting are imported unpublished so they can never be
    added to a cart.
    """
    initial_stock = bootstrap_stock()
    imported = 0
    for item in catalog.ITEMS:
        if db.get_product_by_id(item.sku) is not None:
            continue
        if db.variant_exists(item.sku):
            # A previous catalog import already sells this SKU as part of a
            # different product. Keep that row as the price/stock authority
            # rather than failing startup on the unique constraint.
            logger.warning("store_catalog_sku_already_present sku=%s", item.sku)
            continue
        db.create_product(
            ProductInput(
                name=item.name,
                slug=item.slug,
                base_sku=item.sku,
                description=item.desc,
                category_label=item.category_label,
                featured=item.feature,
                published=not item.restricted,
                variants=[
                    VariantInput(
                        sku=item.sku,
                        upc=item.upc,
                        price_cents=item.price_cents,
                        stock_on_hand=initial_stock,
                    )
                ],
            ),
        )
        imported += 1
    logger.info(
        "store_catalog_bootstrapped products=%d initial_stock=%d",
        imported,
        initial_stock,
    )
    _warn_on_price_drift()
    return imported


def _warn_on_price_drift() -> None:
    """Flag SKUs whose database price no longer matches the menu.

    The database is what checkout charges and what the storefront displays,
    so a drift is not an error, but it usually means the menu was updated
    without updating inventory (or the other way around).
    """
    inventory = db.sku_inventory()
    for item in catalog.ITEMS:
        row = inventory.get(item.sku)
        if row is not None and int(row["price_cents"]) != item.price_cents:
            logger.warning(
                "store_price_drift sku=%s menu_cents=%d database_cents=%d",
                item.sku,
                item.price_cents,
                int(row["price_cents"]),
            )
