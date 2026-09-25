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
    """Import menu items the database lacks and reconcile the ones it has.

    Every menu item becomes one product with one variant keyed by its SKU.
    Prices come from the menu, but stock defaults to zero so a fresh
    production deployment cannot accidentally sell unconfigured items.
    Items that require vetting are imported unpublished so they can never be
    added to a cart. SKUs that already exist keep their stock but take the
    menu's price, and are unpublished if the menu now requires vetting.
    """
    initial_stock = bootstrap_stock()
    imported = 0
    for item in catalog.ITEMS:
        if db.variant_exists(item.sku):
            changes = db.reconcile_menu_item(
                item.sku, item.price_cents, restricted=item.restricted
            )
            if changes["price_updated"]:
                logger.warning(
                    "store_price_synced sku=%s price_cents=%d",
                    item.sku,
                    item.price_cents,
                )
            if changes["unpublished"]:
                logger.warning("store_restricted_item_unpublished sku=%s", item.sku)
            continue
        if db.get_product_by_id(item.sku) is not None:
            # An earlier import created this SKU as a product family whose
            # variants carry -NNN suffixes, so there is no sellable variant
            # with this exact SKU. Leave the family alone and say so.
            logger.warning("store_catalog_sku_is_a_family sku=%s", item.sku)
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
    return imported
