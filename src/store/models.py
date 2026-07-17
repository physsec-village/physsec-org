import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from pydantic import BaseModel, Field, model_validator

BASE_SKU_RE = re.compile(r"^PSV-[A-Z]{3}-\d{3}$")
VARIANT_SKU_RE = re.compile(r"^PSV-[A-Z]{3}-\d{3}(?:-\d{3})?$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class VariantInput(BaseModel):
    sku: str
    name: str = ""
    price_cents: int = Field(ge=0)
    stock: int = Field(ge=0)
    position: int = 0

    @model_validator(mode="after")
    def validate_sku(self):
        self.sku = self.sku.strip().upper()
        if not VARIANT_SKU_RE.match(self.sku):
            raise ValueError("Variant SKU must be a base SKU with an optional -NNN suffix.")
        return self


class ProductInput(BaseModel):
    name: str
    slug: str
    base_sku: str
    description: str = ""
    category_label: str = ""
    featured: bool = False
    published: bool = True
    variants: list[VariantInput]

    @model_validator(mode="after")
    def validate_product(self):
        self.name = self.name.strip()
        self.slug = slugify(self.slug or self.name)
        self.base_sku = self.base_sku.strip().upper()
        self.category_label = self.category_label.strip()
        if not self.name:
            raise ValueError("Product name is required.")
        if not BASE_SKU_RE.match(self.base_sku):
            raise ValueError("Base SKU must match PSV-XXX-NNN.")
        if not self.variants:
            raise ValueError("At least one variant is required.")

        is_multi_variant = len(self.variants) > 1
        seen_skus: set[str] = set()
        for variant in self.variants:
            if variant.sku in seen_skus:
                raise ValueError("Variant SKUs must be unique within a product.")
            seen_skus.add(variant.sku)
            if variant.sku != self.base_sku and not variant.sku.startswith(f"{self.base_sku}-"):
                raise ValueError("All variant SKUs must share the product base SKU prefix.")
            if is_multi_variant and variant.sku == self.base_sku:
                raise ValueError("Multi-variant products must use suffixed variant SKUs.")
            if not is_multi_variant and variant.sku != self.base_sku and not variant.sku.startswith(f"{self.base_sku}-"):
                raise ValueError("Single-variant SKU must be the base SKU or a suffixed SKU.")
        return self

    @property
    def category_code(self) -> str:
        return self.base_sku.split("-")[1]


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "product"


def category_code_from_sku(base_sku: str) -> str:
    base_sku = base_sku.strip().upper()
    if not BASE_SKU_RE.match(base_sku):
        raise ValueError("Base SKU must match PSV-XXX-NNN.")
    return base_sku.split("-")[1]


def cents_from_dollars(value: str) -> int:
    try:
        decimal = Decimal((value or "0").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Prices must be valid dollar amounts.") from exc
    if not decimal.is_finite():
        raise ValueError("Prices must be valid dollar amounts.")
    if decimal < 0:
        raise ValueError("Prices must be zero or greater.")
    try:
        return int((decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("Prices must be valid dollar amounts.") from exc


def dollars_from_cents(value: int) -> str:
    return f"{Decimal(value or 0) / Decimal(100):.2f}"
