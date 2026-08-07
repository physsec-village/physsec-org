"""DEF CON 34 store menu generated from the reviewed Odoo PoS export.

``menu_products.tsv`` is a checked-in snapshot of products that were available
in Point of Sale and assigned to a category whose name ended in ``DC33`` in the
August 7, 2026 export. Keeping the snapshot separate makes future Odoo exports
straightforward to diff and audit.

The ``DC33`` suffix is intentional even though this is the DEF CON 34 menu: it
is the Odoo category suffix selected for this reconciliation.
"""

import re
from collections import defaultdict
from csv import DictReader
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Item:
    """One buyable line on the menu."""

    code: str
    name: str
    price: Decimal
    sku: str | None = None
    price_suffix: str = ""
    desc: str = ""
    note: str = ""
    bullets: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    feature: bool = False
    image: str = ""


@dataclass(frozen=True)
class Group:
    """A run of items under one sub-heading."""

    title: str = ""
    tag: str = ""
    lede: str = ""
    prose: tuple[str, ...] = ()
    items: tuple[Item, ...] = ()
    table: dict | None = None


@dataclass(frozen=True)
class Section:
    """A jump-linked chunk of the menu."""

    slug: str
    title: str
    blurb: str = ""
    groups: tuple[Group, ...] = field(default_factory=tuple)


def _load_menu() -> tuple[Section, ...]:
    path = Path(__file__).with_name("menu_products.tsv")
    with path.open(encoding="utf-8", newline="") as source:
        rows = tuple(DictReader(source, delimiter="\t"))

    category_titles = {
        "Bypass Tools": "Bypass Tools",
        "Covert Instruments": "Covert Instruments",
        "Keys": "Keys",
        "Misc": "Other Gear & Swag",
        "Sets": "Sets",
    }
    unmapped_categories = {row["category"] for row in rows} - category_titles.keys()
    if unmapped_categories:
        names = ", ".join(sorted(unmapped_categories))
        raise ValueError(f"Unmapped menu categories: {names}")

    sections = []
    for category, title in category_titles.items():
        category_rows = (row for row in rows if row["category"] == category)
        items = []
        fallback_counts: defaultdict[str, int] = defaultdict(int)
        for row in category_rows:
            sku = row["sku"] or None
            if sku:
                code = sku.removeprefix("PSV-").replace("-", "")
            else:
                name_slug = re.sub(r"[^A-Z0-9]+", "-", row["name"].upper()).strip("-")
                base_code = f"ODOO-{category.upper().replace(' ', '-')}-{name_slug}"
                fallback_counts[base_code] += 1
                occurrence = fallback_counts[base_code]
                code = base_code if occurrence == 1 else f"{base_code}-{occurrence}"
            image_name = f"{code.lower()}.webp"
            image = image_name if (path.parent.parent / "static/images/menu" / image_name).is_file() else ""
            items.append(
                Item(
                    code=code,
                    name=row["name"],
                    price=Decimal(row["price"]),
                    sku=sku,
                    image=image,
                )
            )
        if items:
            sections.append(
                Section(
                    slug=category.lower().replace(" ", "-"),
                    title=title,
                    groups=(Group(items=tuple(items)),),
                )
            )
    return tuple(sections)


MENU = _load_menu()
FOOTNOTES: tuple[str, ...] = ()
ITEMS_BY_CODE: dict[str, Item] = {
    item.code: item
    for section in MENU
    for group in section.groups
    for item in group.items
}
