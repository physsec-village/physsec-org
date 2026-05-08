PRODUCTS = [
    {
        "slug": "under-door-tool",
        "name": "Under-Door Bypass Tool",
        "category": "Tools",
        "price_cents": 2500,
        "price_display": "$25.00",
        "description_short": "Flexible under-door tool for lever handle bypass demonstrations.",
        "description_long": "A professional-grade flexible bypass tool designed for security research and training. Used to demonstrate the vulnerability of lever-handle doors without deadbolts to under-door attacks. Essential for physical penetration testing engagements.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "shim-set",
        "name": "Padlock Shim Set",
        "category": "Tools",
        "price_cents": 1500,
        "price_display": "$15.00",
        "description_short": "Set of padlock shims for bypass training and demonstrations.",
        "description_long": "A complete set of precision-cut padlock shims in multiple sizes. Ideal for teaching shim-based bypass techniques in controlled training environments. Includes a quick-start guide covering common padlock vulnerabilities.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "traveler-hook",
        "name": "Traveler Hook",
        "category": "Tools",
        "price_cents": 3500,
        "price_display": "$35.00",
        "description_short": "Compact traveler hook for latch bypass and security assessments.",
        "description_long": "A compact, purpose-built traveler hook for demonstrating latch bypass techniques on improperly installed or vulnerable door hardware. Folds flat for easy transport. A staple tool in any physical security assessor's kit.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "common-keys-set",
        "name": "Common Keyed-Alike Key Set",
        "category": "Tools",
        "price_cents": 4500,
        "price_display": "$45.00",
        "description_short": "Collection of commonly keyed-alike keys for cabinets, elevators, and panels.",
        "description_long": "A curated set of the most commonly encountered keyed-alike keys used in commercial infrastructure — including elevator override keys, cabinet keys, and utility panel keys. Invaluable for demonstrating the risks of widely shared key patterns during security assessments.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "rfid-fobs-blank",
        "name": "Blank RFID Fobs (5-pack)",
        "category": "Electronics",
        "price_cents": 2000,
        "price_display": "$20.00",
        "description_short": "Pack of 5 writable RFID fobs compatible with common access systems.",
        "description_long": "Five T5577 writable RFID key fobs compatible with most 125kHz access control systems. Ideal for cloning demonstrations and RFID security research. Works with Proxmark, Flipper Zero, and other common RFID tools.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "proxmark3-ez",
        "name": "Proxmark 3 EZ",
        "category": "Electronics",
        "price_cents": 7500,
        "price_display": "$75.00",
        "description_short": "Entry-level Proxmark 3 for RFID research and access control testing.",
        "description_long": "The Proxmark 3 EZ is an accessible entry point into RFID security research. Supports reading, writing, and emulating both low-frequency (125kHz) and high-frequency (13.56MHz) credentials. Comes pre-flashed with the latest Iceman firmware and includes a USB-C cable and antenna set.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "psv-tshirt",
        "name": "PSV Branded T-Shirt",
        "category": "Merch",
        "price_cents": 2800,
        "price_display": "$28.00",
        "description_short": "Official Physical Security Village t-shirt with running man logo.",
        "description_long": "Soft-blend tri-color t-shirt featuring the iconic PSV running man logo on the front and event history on the back. Available in multiple sizes. Show your support for the physical security community.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "psv-patches",
        "name": "PSV Patches (3-pack)",
        "category": "Merch",
        "price_cents": 1200,
        "price_display": "$12.00",
        "description_short": "Set of 3 embroidered PSV patches for bags, jackets, and lanyards.",
        "description_long": "Three embroidered patches featuring PSV branding and iconography. Iron-on or sew-on backing. Perfect for your conference bag, jacket, or lanyard collection. Each pack includes one large logo patch and two smaller accent patches.",
        "image": None,
        "in_stock": True,
    },
    {
        "slug": "psv-stickers",
        "name": "PSV Sticker Pack",
        "category": "Merch",
        "price_cents": 800,
        "price_display": "$8.00",
        "description_short": "Assorted pack of die-cut PSV stickers for laptops and gear.",
        "description_long": "A pack of 8 die-cut vinyl stickers featuring PSV logos, slogans, and original artwork from the physical security community. Weatherproof and scratch-resistant. Deck out your laptop, water bottle, or pelican case.",
        "image": None,
        "in_stock": True,
    },
]


def get_all_products():
    return PRODUCTS


def get_product_by_slug(slug):
    for product in PRODUCTS:
        if product["slug"] == slug:
            return product
    return None


def get_categories():
    return sorted({p["category"] for p in PRODUCTS})
