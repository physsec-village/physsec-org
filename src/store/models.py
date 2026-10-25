"""Validated admin inputs and small value helpers for the store domain."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import BaseModel, Field, model_validator

# Matches the check constraint on store.products.slug and store.collections.slug.
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
# Prices and stock are PostgreSQL integer columns.
MAX_DB_INT = 2**31 - 1


def _optional(value: str | None) -> str | None:
    """Store blank SKUs and UPCs as NULL; the schema rejects empty strings."""
    value = (value or "").strip()
    return value or None


class VariantInput(BaseModel):
    """A new variant. SKUs are optional, opaque inventory identifiers."""

    name: str = ""
    sku: str | None = Field(default=None, max_length=64)
    upc: str | None = Field(default=None, max_length=32)
    price_cents: int = Field(ge=0, le=MAX_DB_INT)
    stock_on_hand: int = Field(default=0, ge=0, le=MAX_DB_INT)

    @model_validator(mode="after")
    def strip_text(self) -> VariantInput:
        self.name = self.name.strip()
        self.sku = _optional(self.sku)
        self.upc = _optional(self.upc)
        return self


class VariantUpdate(VariantInput):
    """An admin edit to an existing variant.

    `expected_stock` is the stock on hand the admin was shown, so the database
    can reject an edit made against a stale value. Unpublishing a variant
    retires it: shoppers no longer see it, but past orders keep it.
    """

    id: int
    stock_on_hand: int = Field(ge=0, le=MAX_DB_INT)
    expected_stock: int = Field(ge=0, le=MAX_DB_INT)
    published: bool = True


class ProductInput(BaseModel):
    """Product details an admin can set. A blank slug is derived from the name."""

    name: str
    slug: str = ""
    description: str = ""
    features: list[str] = []
    featured: bool = False
    published: bool = False
    group_ids: list[int] = []

    @model_validator(mode="after")
    def validate_product(self) -> ProductInput:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Product name is required.")
        self.slug = self.slug.strip().lower() or slugify(self.name)
        if not SLUG_RE.fullmatch(self.slug):
            raise ValueError(
                "URL slug may only contain lowercase letters, digits and single "
                "hyphens between them."
            )
        self.description = self.description.strip()
        self.features = [line.strip() for line in self.features if line.strip()]
        return self


def slugify(value: str) -> str:
    return _SLUG_SEPARATORS.sub("-", value.lower()).strip("-") or "product"


def cents_from_dollars(value: str) -> int:
    try:
        amount = Decimal((value or "0").strip())
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Prices must be valid non-negative dollar amounts.") from exc


def dollars_from_cents(value: int) -> str:
    return f"{Decimal(value or 0) / Decimal(100):.2f}"
