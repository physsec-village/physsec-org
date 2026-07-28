"""PSV store catalog.

Products live in products.tsv (name, SKU, UPC). SKUs with four segments
(PSV-CAT-NNN-VVV) are variants and get grouped into a single product whose
shared name and per-variant labels are derived from the member names.

Prices are deliberately deterministic placeholders (hash of the SKU plus a
per-category base, with overrides for well-known items) carried over from the
approved store design; replace with real pricing data when it exists.
"""

import logging
import re
from dataclasses import dataclass, field
from math import floor
from pathlib import Path

CATEGORY_LABELS = {
    "BYP": "Bypass Tools",
    "KYS": "Keys",
    "RFID": "RFID",
    "MSC": "Gear",
    "MRC": "Merch",
}

CATEGORY_ORDER = ("BYP", "KYS", "RFID", "MSC", "MRC")
logger = logging.getLogger(__name__)

CATEGORY_BLURBS = {
    "BYP": "Shims, jigglers, slips, and picks for hands-on bypass practice.",
    "KYS": "Elevator, equipment, and utility keys — all cut keyed-alike.",
    "RFID": "Read, study, and clone access credentials in a controlled lab.",
    "MSC": "Practical gear for the physical security bench and go-bag.",
    "MRC": "Wear the village. Soft, durable, unmistakably PSV.",
}

ALL_PRODUCTS_BLURB = "Every tool, key, and kit on the PSV bench, in one grid."

CATEGORY_DESCRIPTIONS = {
    "BYP": "A field-proven bypass tool for hands-on practice and authorized "
    "entry work. Machined to hold up to repeated bench use.",
    "KYS": "A commonly encountered utility key. Every PSV key is cut "
    "keyed-alike, so it drops right into the rest of your set for training "
    "and demonstrations.",
    "RFID": "RFID research hardware for reading, studying, and cloning access "
    "credentials in a controlled lab environment.",
    "MSC": "Practical gear for the physical security bench and go-bag.",
    "MRC": "Represent the village. Soft, durable, and unmistakably PSV.",
}

_PRICE_OVERRIDES = (
    (re.compile(r"proxmark"), 89.99),
    (re.compile(r"^handcuffs$"), 24.99),
    (re.compile(r"lockpicking practice"), 21.99),
    (re.compile(r"screwdriver set"), 29.99),
    (re.compile(r"uv pen"), 8.99),
    (re.compile(r"cable key ring"), 5.99),
    (re.compile(r"zener"), 14.99),
)

_PRICE_BASES = {"BYP": 14, "KYS": 8, "MRC": 27, "MSC": 18, "RFID": 16}

_FEATURED_PATTERNS = (
    re.compile(r"proxmark", re.IGNORECASE),
    re.compile(r"^lishi", re.IGNORECASE),
    re.compile(r"^medeco bump", re.IGNORECASE),
    re.compile(r"unauthorised personnel shirt", re.IGNORECASE),
    re.compile(r"^handcuffs$", re.IGNORECASE),
)

HERO_PRODUCT_ID = "PSV-RFID-001"

FREE_SHIPPING_THRESHOLD = 75
FLAT_SHIPPING = 7.99


@dataclass(frozen=True)
class Variant:
    code: str
    label: str
    sku: str
    upc: str


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    cat: str
    sku: str
    upc: str
    price: float
    variants: tuple[Variant, ...] = field(default=())

    @property
    def cat_label(self) -> str:
        return CATEGORY_LABELS.get(self.cat, self.cat)

    @property
    def is_key(self) -> bool:
        return self.cat == "KYS"

    @property
    def price_str(self) -> str:
        return f"${self.price:.2f}"

    @property
    def desc(self) -> str:
        return CATEGORY_DESCRIPTIONS.get(
            self.cat, "A Physical Security Village catalog item."
        )

    @property
    def search_text(self) -> str:
        parts = [self.name, self.sku, self.cat_label]
        parts.extend(v.label for v in self.variants)
        parts.extend(v.sku for v in self.variants)
        return " ".join(parts).lower()


def _price_for(cat: str, sku: str, name: str) -> float:
    lc = name.lower()
    for pattern, price in _PRICE_OVERRIDES:
        if pattern.search(lc):
            return price
    h = 0
    for ch in sku:
        h = (h * 33 + ord(ch)) & 0xFFFFFFFF
    d = _PRICE_BASES.get(cat, 16) + h % 12
    if "patch" in lc:
        return 10.99
    if re.search(r"\b(set|kit|bundle|companion)\b", lc):
        d = floor(d * 2.1 + 0.5) + 15
    return round(d - 0.01, 2)


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"^[\s\-–(]+|[\s\-–(]+$", "", s).strip()


def _char_lcp(names: list[str]) -> str:
    prefix = names[0]
    for name in names:
        while not name.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix


def _derive_group(names: list[str]) -> tuple[str, list[str]]:
    """Split variant names into a shared product name and per-variant labels."""
    tokens = [n.split() for n in names]
    min_len = min(len(t) for t in tokens)
    prefix = 0
    while prefix < min_len and all(t[prefix] == tokens[0][prefix] for t in tokens):
        prefix += 1
    suffix = 0
    while suffix < min_len - prefix and all(
        t[len(t) - 1 - suffix] == tokens[0][len(tokens[0]) - 1 - suffix] for t in tokens
    ):
        suffix += 1
    shared = tokens[0][:prefix] + (tokens[0][-suffix:] if suffix else [])
    name = _clean(" ".join(shared))
    labels = [
        _clean(" ".join(t[prefix : len(t) - suffix if suffix else len(t)]))
        for t in tokens
    ]
    if len(name.replace(" ", "")) < 2:
        lcp = _clean(_char_lcp(names))
        if len(lcp.replace(" ", "")) >= 3:
            name = lcp + ("x" if re.search(r"\d$", lcp) else " Series")
        else:
            name = names[0] + " (assorted)"
        labels = list(names)
    labels = [label or names[i] for i, label in enumerate(labels)]
    return name, labels


def _load_rows() -> list[tuple[str, str, str]]:
    raw = (Path(__file__).parent / "products.tsv").read_text(encoding="utf-8")
    skip = re.compile(r"reserved|do not use", re.IGNORECASE)
    rows = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) != 3:
            logger.warning("Skipping malformed catalog row line=%d", line_number)
            continue
        name, sku, upc = parts
        if name and sku and not skip.search(name):
            rows.append((name, sku, upc))
    return rows


def _build_products() -> tuple[Product, ...]:
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    singles: list[tuple[str, str, str]] = []
    for row in _load_rows():
        sku_parts = row[1].split("-")
        if len(sku_parts) >= 4:
            grouped.setdefault("-".join(sku_parts[:3]), []).append(row)
        else:
            singles.append(row)

    products = []
    for name, sku, upc in singles:
        cat = sku.split("-")[1]
        products.append(
            Product(
                id=sku,
                name=name,
                cat=cat,
                sku=sku,
                upc=upc,
                price=_price_for(cat, sku, name),
            )
        )
    for base, members in grouped.items():
        cat = base.split("-")[1]
        if len(members) == 1:
            name, sku, upc = members[0]
            products.append(
                Product(
                    id=sku,
                    name=name,
                    cat=cat,
                    sku=sku,
                    upc=upc,
                    price=_price_for(cat, sku, name),
                )
            )
            continue
        name, labels = _derive_group([m[0] for m in members])
        variants = tuple(
            Variant(code=sku.split("-")[-1], label=label, sku=sku, upc=upc)
            for (_, sku, upc), label in zip(members, labels)
        )
        first = members[0]
        products.append(
            Product(
                id=base,
                name=name,
                cat=cat,
                sku=first[1],
                upc=first[2],
                price=_price_for(cat, first[1], name),
                variants=variants,
            )
        )

    products.sort(
        key=lambda product: (
            (
                CATEGORY_ORDER.index(product.cat)
                if product.cat in CATEGORY_ORDER
                else len(CATEGORY_ORDER)
            ),
            product.name.casefold(),
        )
    )
    return tuple(products)


PRODUCTS = _build_products()
PRODUCT_MAP = {p.id: p for p in PRODUCTS}


def _pick_featured() -> tuple[Product, ...]:
    picks: list[Product] = []
    for pattern in _FEATURED_PATTERNS:
        hit = next(
            (p for p in PRODUCTS if pattern.search(p.name) and p not in picks), None
        )
        if hit:
            picks.append(hit)
    return tuple(picks[:4])


FEATURED = _pick_featured()
HERO = PRODUCT_MAP.get(HERO_PRODUCT_ID) or (
    FEATURED[0] if FEATURED else PRODUCTS[0] if PRODUCTS else None
)


def category_hub() -> list[dict]:
    return [
        {
            "key": cat,
            "label": CATEGORY_LABELS[cat],
            "blurb": CATEGORY_BLURBS[cat],
            "count": sum(1 for p in PRODUCTS if p.cat == cat),
        }
        for cat in CATEGORY_ORDER
    ]


def related_products(product: Product, limit: int = 4) -> list[Product]:
    return [p for p in PRODUCTS if p.cat == product.cat and p.id != product.id][:limit]


def catalog_json() -> dict:
    """Minimal product map embedded in store pages for the client-side cart."""
    return {
        p.id: {
            "name": p.name,
            "price": p.price,
            "variants": [{"code": v.code, "label": v.label} for v in p.variants],
        }
        for p in PRODUCTS
    }
