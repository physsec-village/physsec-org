"""Storefront catalog derived from the DEF CON store menu.

`src/menu.py` is the single source of truth for what PSV sells: names,
prices, copy, photos, and how items are grouped. This module reshapes that
menu into the online store's collections and gives every item a stable SKU,
a URL slug, and a UPC (looked up from `products.tsv`) so it can be seeded
into PostgreSQL and sold through Stripe Checkout.

Prices here are the menu's list prices in integer cents. Checkout always
charges the price stored in the database, which the bootstrap seeds from this
module; the storefront displays the database price so what is shown is what
is charged.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..dependencies import strip_footnotes
from ..menu import FOOTNOTES, MENU, Item
from .models import slugify

# Menu copy that only makes sense at the event table.
_EVENT_COPY = (
    (re.compile(r"\s+for sale at DEF CON \d+"), " in the store"),
    (re.compile(r"\bDEF CON \d+\b"), "the Village"),
)

# Section titles carry a price hint ("Lishi Tools — $100 Each"); the store
# shows prices per item, so the hint becomes a small tag instead.
_TITLE_PRICE_TAG = re.compile(r"\s+[—–-]\s+(\$\d+\s+each)$", re.IGNORECASE)

# Footnote markers ("[^2]") in menu copy point into FOOTNOTES. The first
# footnote is the FEO-K1 vetting rule: an item carrying it cannot be shipped
# without vetting.
_FOOTNOTE_REF = re.compile(r"\[\^(\d+)\]")
_VETTING_FOOTNOTE = 1

# Placeholder SKUs for menu items that do not have one yet. The prefix keeps
# them out of the real PSV-BYP/KYS/... families until inventory assigns one.
PLACEHOLDER_CATEGORY = "TBD"

CATEGORY_LABELS = {
    "BYP": "Bypass Tools",
    "KYS": "Keys",
    "MSC": "Gear",
    "RFID": "RFID",
    PLACEHOLDER_CATEGORY: "Sets & Bundles",
}

HERO_CODE = "BYP012"
FEATURED_CODES = (
    "BYP010",
    "BYP014002",
    "TBD014",
    "MSC003",
    "KYS028001",
    "BYP007",
)
COLLECTION_COVERS = {
    "bypass-tools": "byp010.webp",
    "lockpicking": "byp003.webp",
    "lishi": "byp014002.webp",
    "keyed-alike": "kys003.webp",
    "specialty-keys": "tbd014.webp",
    "elevator": "kys028001.webp",
    "gear": "rfid002002.webp",
}


@dataclass(frozen=True)
class StoreItem:
    """One sellable menu line, addressed by SKU."""

    code: str
    sku: str
    slug: str
    name: str
    price_cents: int
    price_suffix: str = ""
    desc: str = ""
    note: str = ""
    bullets: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    image: str = ""
    upc: str = ""
    feature: bool = False
    footnotes: tuple[str, ...] = ()
    restricted: bool = False
    restricted_reason: str = ""
    collection_slug: str = ""
    group_title: str = ""

    @property
    def category_code(self) -> str:
        return self.sku.split("-")[1]

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category_code, self.category_code)

    @property
    def placeholder_sku(self) -> bool:
        return self.category_code == PLACEHOLDER_CATEGORY

    @property
    def search_text(self) -> str:
        parts = [self.name, self.sku, self.code, self.desc, self.group_title]
        parts.extend(self.bullets)
        return " ".join(parts).casefold()


@dataclass(frozen=True)
class StoreGroup:
    """A run of items under one sub-heading inside a collection."""

    title: str = ""
    tag: str = ""
    lede: str = ""
    prose: tuple[str, ...] = ()
    items: tuple[StoreItem, ...] = ()
    table: dict | None = None
    anchor: str = ""


@dataclass(frozen=True)
class Collection:
    """A menu section, presented as its own store page."""

    slug: str
    title: str
    tag: str = ""
    blurb: str = ""
    cover: str = ""
    groups: tuple[StoreGroup, ...] = field(default_factory=tuple)

    @property
    def items(self) -> tuple[StoreItem, ...]:
        seen: set[str] = set()
        ordered: list[StoreItem] = []
        for group in self.groups:
            for item in group.items:
                if item.sku not in seen:
                    seen.add(item.sku)
                    ordered.append(item)
        return tuple(ordered)

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def titled_groups(self) -> tuple[StoreGroup, ...]:
        """Groups worth a jump link: titled, with items or a reference table."""
        return tuple(
            group
            for group in self.groups
            if group.title and (group.items or group.table)
        )


def _scrub(text: str) -> str:
    for pattern, replacement in _EVENT_COPY:
        text = pattern.sub(replacement, text)
    return text


def _clean(text: str) -> str:
    return _scrub(strip_footnotes(text)).strip()


def _load_upcs() -> dict[str, str]:
    path = Path(__file__).parent / "products.tsv"
    upcs: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) >= 3 and row[1].strip():
                upcs[row[1].strip().upper()] = row[2].strip()
    return upcs


def sku_for(item: Item) -> str:
    """Return the inventory SKU, or a placeholder derived from the menu code."""
    if item.sku:
        return item.sku.strip().upper()
    code = item.code.strip().upper()
    return f"PSV-{PLACEHOLDER_CATEGORY}-{code.removeprefix(PLACEHOLDER_CATEGORY)}"


def _footnote_numbers(item: Item) -> tuple[int, ...]:
    """Footnote numbers referenced anywhere in the item's copy, in order."""
    found: list[int] = []
    for text in (item.name, item.desc, item.note, *item.bullets, *item.details):
        for match in _FOOTNOTE_REF.finditer(text):
            number = int(match.group(1))
            if number not in found and 1 <= number <= len(FOOTNOTES):
                found.append(number)
    return tuple(found)


def _price_tag(title: str, prices: list[int]) -> tuple[str, str]:
    """Split a "$N each" hint off a section title.

    The hint only becomes a tag when every item in the section really costs
    that much; the elevator section says "$10 each" but also sells sets.
    """
    match = _TITLE_PRICE_TAG.search(title)
    if not match:
        return title, ""
    clean = _TITLE_PRICE_TAG.sub("", title).strip()
    amount_cents = int(re.sub(r"\D", "", match.group(1))) * 100
    if prices and all(price == amount_cents for price in prices):
        return clean, match.group(1).lower()
    return clean, ""


def _build() -> tuple[tuple[Collection, ...], dict[str, StoreItem]]:
    upcs = _load_upcs()
    by_sku: dict[str, StoreItem] = {}
    slugs: dict[str, str] = {}
    collections: list[Collection] = []

    for section in MENU:
        groups: list[StoreGroup] = []
        for index, group in enumerate(section.groups):
            items: list[StoreItem] = []
            for raw in group.items:
                sku = sku_for(raw)
                existing = by_sku.get(sku)
                if existing is not None:
                    if existing.price_cents != raw.price * 100:
                        raise ValueError(f"Menu lists {sku} at two prices.")
                    items.append(existing)
                    continue
                name = _clean(raw.name)
                slug = slugify(name)
                if slugs.get(slug, sku) != sku:
                    slug = f"{slug}-{raw.code.lower()}"
                slugs[slug] = sku
                footnotes = _footnote_numbers(raw)
                restricted = _VETTING_FOOTNOTE in footnotes
                item = StoreItem(
                    code=raw.code,
                    sku=sku,
                    slug=slug,
                    name=name,
                    price_cents=raw.price * 100,
                    price_suffix=raw.price_suffix,
                    desc=_clean(raw.desc),
                    note=_clean(raw.note),
                    bullets=tuple(_clean(bullet) for bullet in raw.bullets),
                    details=tuple(_clean(detail) for detail in raw.details),
                    image=raw.image,
                    upc=upcs.get(sku, ""),
                    feature=raw.feature,
                    footnotes=tuple(FOOTNOTES[number - 1] for number in footnotes),
                    restricted=restricted,
                    restricted_reason=FOOTNOTES[_VETTING_FOOTNOTE - 1]
                    if restricted
                    else "",
                    collection_slug=section.slug,
                    group_title=group.title,
                )
                by_sku[sku] = item
                items.append(item)
            groups.append(
                StoreGroup(
                    title=group.title,
                    tag=group.tag,
                    lede=_clean(group.lede),
                    prose=tuple(_clean(text) for text in group.prose),
                    items=tuple(items),
                    table=group.table,
                    anchor=slugify(group.title) if group.title else f"group-{index}",
                )
            )
        title, tag = _price_tag(
            section.title,
            [item.price_cents for group in groups for item in group.items],
        )
        cover = COLLECTION_COVERS.get(section.slug) or next(
            (item.image for group in groups for item in group.items if item.image),
            "",
        )
        collections.append(
            Collection(
                slug=section.slug,
                title=title,
                tag=tag,
                blurb=_clean(section.blurb),
                cover=cover,
                groups=tuple(groups),
            )
        )
    return tuple(collections), by_sku


COLLECTIONS, ITEMS_BY_SKU = _build()
COLLECTION_MAP = {collection.slug: collection for collection in COLLECTIONS}
ITEMS: tuple[StoreItem, ...] = tuple(ITEMS_BY_SKU.values())
ITEMS_BY_SLUG = {item.slug: item for item in ITEMS}
ITEMS_BY_CODE = {item.code: item for item in ITEMS}
HERO = ITEMS_BY_CODE[HERO_CODE]
FEATURED = tuple(ITEMS_BY_CODE[code] for code in FEATURED_CODES)


def collection_for(item: StoreItem) -> Collection:
    return COLLECTION_MAP[item.collection_slug]


def group_for(item: StoreItem) -> StoreGroup:
    collection = collection_for(item)
    return next(
        group
        for group in collection.groups
        if any(i.sku == item.sku for i in group.items)
    )


def related_items(item: StoreItem, limit: int = 4) -> tuple[StoreItem, ...]:
    """Prefer siblings from the same group, then the rest of the collection."""
    group = group_for(item)
    collection = collection_for(item)
    ordered = [i for i in group.items if i.sku != item.sku]
    ordered.extend(
        i for i in collection.items if i.sku != item.sku and i not in ordered
    )
    return tuple(ordered[:limit])


def search(query: str) -> tuple[StoreItem, ...]:
    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return ()
    return tuple(
        item for item in ITEMS if all(term in item.search_text for term in terms)
    )
