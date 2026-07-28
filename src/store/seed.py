"""Resumable import of the storefront design catalog into PostgreSQL."""

from __future__ import annotations

import logging

from . import catalog, db
from .config import bootstrap_stock
from .models import ProductInput, VariantInput, cents_from_dollars

logger = logging.getLogger(__name__)


def bootstrap_catalog() -> int:
    """Serialize catalog bootstrap across concurrent application starts."""
    with db.catalog_bootstrap_lock():
        return _bootstrap_catalog()


def _bootstrap_catalog() -> int:
    """Import the bundled catalog only when the database has no products.

    Imports resume per base SKU. Prices come from the approved design data, but
    stock defaults to zero so a fresh production deployment cannot accidentally
    sell unconfigured items.
    """
    initial_stock = bootstrap_stock()
    grouped: dict[str, list[catalog.Product]] = {}
    for product in catalog.PRODUCTS:
        grouped.setdefault("-".join(product.id.split("-")[:3]), []).append(product)

    imported = 0
    for base_sku, members in grouped.items():
        if db.get_product_by_id(base_sku) is not None:
            continue
        product = members[0]
        source_variants: list[tuple[catalog.Variant, catalog.Product]] = []
        for member in members:
            variants = member.variants or (
                catalog.Variant(code="_", label="", sku=member.sku, upc=member.upc),
            )
            source_variants.extend((variant, member) for variant in variants)
        variants = [
            VariantInput(
                sku=variant.sku,
                name=variant.label or (member.name if len(members) > 1 else ""),
                upc=variant.upc,
                price_cents=cents_from_dollars(str(member.price)),
                stock_on_hand=initial_stock,
                position=position,
            )
            for position, (variant, member) in enumerate(source_variants)
        ]
        db.create_product(
            ProductInput(
                name=product.name,
                slug=product.id,
                base_sku=base_sku,
                description=product.desc,
                category_label=product.cat_label,
                featured=any(member in catalog.FEATURED for member in members),
                published=True,
                variants=variants,
            ),
        )
        imported += 1
    logger.info(
        "store_catalog_bootstrapped products=%d initial_stock=%d",
        imported,
        initial_stock,
    )
    return imported
