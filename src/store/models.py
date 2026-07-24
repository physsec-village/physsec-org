"""Validated inputs and small value helpers for the store domain."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import AliasChoices, BaseModel, Field, model_validator

# Category codes in the real inventory include RFID.  Keep the grammar strict
# while avoiding the three-character assumption made by the original backend.
BASE_SKU_RE = re.compile(r"^PSV-[A-Z0-9]{3,8}-\d{3}$")
VARIANT_SKU_RE = re.compile(r"^PSV-[A-Z0-9]{3,8}-\d{3}(?:-\d{3})?$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class VariantInput(BaseModel):
    sku: str
    name: str = ""
    upc: str = ""
    price_cents: int = Field(ge=0)
    stock_on_hand: int = Field(
        default=0, ge=0, validation_alias=AliasChoices("stock_on_hand", "stock")
    )
    position: int = 0

    @model_validator(mode="after")
    def validate_sku(self) -> VariantInput:
        self.sku = self.sku.strip().upper()
        self.name = self.name.strip()
        self.upc = self.upc.strip()
        if not VARIANT_SKU_RE.fullmatch(self.sku):
            raise ValueError(
                "Variant SKU must be PSV-CATEGORY-NNN with an optional -NNN suffix."
            )
        return self

    @property
    def stock(self) -> int:
        """Compatibility accessor for older form code."""
        return self.stock_on_hand


class ProductInput(BaseModel):
    name: str
    slug: str = ""
    base_sku: str
    description: str = ""
    category_label: str = ""
    featured: bool = False
    published: bool = True
    variants: list[VariantInput]

    @model_validator(mode="after")
    def validate_product(self) -> ProductInput:
        self.name = self.name.strip()
        self.slug = slugify(self.slug or self.name)
        self.base_sku = self.base_sku.strip().upper()
        self.category_label = self.category_label.strip()
        if not self.name:
            raise ValueError("Product name is required.")
        if not BASE_SKU_RE.fullmatch(self.base_sku):
            raise ValueError("Base SKU must match PSV-CATEGORY-NNN.")
        if not self.variants:
            raise ValueError("At least one variant is required.")
        seen: set[str] = set()
        for variant in self.variants:
            if variant.sku in seen:
                raise ValueError("Variant SKUs must be unique within a product.")
            seen.add(variant.sku)
            if variant.sku != self.base_sku and not variant.sku.startswith(
                f"{self.base_sku}-"
            ):
                raise ValueError("All variant SKUs must share the base SKU prefix.")
        return self

    @property
    def category_code(self) -> str:
        return category_code_from_sku(self.base_sku)


def slugify(value: str) -> str:
    return SLUG_RE.sub("-", value.lower()).strip("-") or "product"


def category_code_from_sku(base_sku: str) -> str:
    normalized = base_sku.strip().upper()
    if not BASE_SKU_RE.fullmatch(normalized):
        raise ValueError("Base SKU must match PSV-CATEGORY-NNN.")
    return normalized.split("-")[1]


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
