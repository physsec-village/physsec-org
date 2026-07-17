import os

from . import db
from .models import ProductInput, VariantInput


def seed_mock_data() -> None:
    if os.getenv("STORE_SEED_MOCK_DATA") != "true" or db.products_count() > 0:
        return

    categories = {"KYS": "Keys", "MRC": "Apparel"}
    for code, label in categories.items():
        db.upsert_category(code, label)

    products = [
        {
            "name": "FEO K1 Key",
            "base_sku": "PSV-KYS-023",
            "description": "A pre-cut common keyed-alike key for physical security village training and controlled demonstrations. Intended for lab discussion around shared fleet and facility keying practices.",
            "variants": [("", "PSV-KYS-023", 800, 34)],
        },
        {
            "name": "Forklift Key (Generic)",
            "base_sku": "PSV-KYS-024",
            "description": "A generic forklift key used in hands-on demos about equipment access and keyed-alike operational risk. Useful for supervised training tables and defensive awareness.",
            "variants": [("", "PSV-KYS-024", 800, 42)],
        },
        {
            "name": "Kone Elevator Keys",
            "base_sku": "PSV-KYS-025",
            "description": "Common elevator service key profiles for classroom comparison and physical security village demonstrations. These are stocked for training conversations about access control boundaries.",
            "featured": True,
            "variants": [(f"Kone {i}", f"PSV-KYS-025-{i:03}", 1000, 12 + i) for i in range(1, 6)],
        },
        {
            "name": "Schlage IC Core Keys",
            "base_sku": "PSV-KYS-026",
            "description": "Interchangeable core control and operating key examples for supervised lock hardware education. Use them to explain key control, labeling, and storage discipline.",
            "variants": [
                ("ICA (Black)", "PSV-KYS-026-001", 1200, 28),
                ("ICA (Brass)", "PSV-KYS-026-002", 1200, 22),
                ("ICB", "PSV-KYS-026-003", 1200, 18),
                ("ICC", "PSV-KYS-026-004", 1200, 16),
            ],
        },
        {
            "name": "Skyjack Key",
            "base_sku": "PSV-KYS-027",
            "description": "A common lift equipment key for demos on jobsite equipment access and shared-key assumptions. Provided for controlled training and awareness exercises.",
            "variants": [("", "PSV-KYS-027", 800, 38)],
        },
        {
            "name": "X400X Series Keys",
            "base_sku": "PSV-KYS-028",
            "description": "A set of common X400X key profiles used to discuss recurring keyed-alike patterns in the field. Individual keys and a training set are available for lab use.",
            "featured": True,
            "variants": [(f"X400{i}", f"PSV-KYS-028-{i:03}", 900, 10 + i) for i in range(1, 10)]
            + [("Set of MAD X4001-8", "PSV-KYS-028-990", 6000, 14)],
        },
        {
            "name": "CAT Master Disconnect Key",
            "base_sku": "PSV-KYS-029",
            "description": "A master disconnect key for training conversations around equipment isolation, storage, and control. Designed for demonstration in physical security village settings.",
            "variants": [("", "PSV-KYS-029", 800, 44)],
        },
        {
            "name": "Forklift Key (Mitsubishi)",
            "base_sku": "PSV-KYS-030",
            "description": "A Mitsubishi-style forklift key for supervised equipment access demonstrations. It supports practical discussions about fleet key reuse and asset control.",
            "variants": [("", "PSV-KYS-030", 800, 36)],
        },
        {
            "name": "Unauthorised Personnel Shirt",
            "base_sku": "PSV-MRC-001",
            "description": "A village shirt for event days, lock labs, and hallway conversations. Printed for supporters who want the physical security theme without pretending a badge is a control.",
            "featured": True,
            "variants": [
                ("XXS", "PSV-MRC-001-001", 2500, 10),
                ("XS", "PSV-MRC-001-002", 2500, 14),
                ("S", "PSV-MRC-001-003", 2500, 26),
                ("M", "PSV-MRC-001-004", 2500, 48),
                ("L", "PSV-MRC-001-005", 2500, 52),
                ("XL", "PSV-MRC-001-006", 2500, 32),
                ("XXL", "PSV-MRC-001-007", 2500, 18),
            ],
        },
        {
            "name": "PSV Sticker Pack",
            "base_sku": "PSV-MRC-002",
            "description": "A small sticker pack for cases, laptops, and workshop gear. It is an easy way to support the village and mark your kit after a training session.",
            "featured": True,
            "variants": [("", "PSV-MRC-002", 500, 60)],
        },
    ]

    for product in products:
        base_sku = product["base_sku"]
        category_code = base_sku.split("-")[1]
        variants = [
            VariantInput(
                name=name,
                sku=sku,
                price_cents=price_cents,
                stock=stock,
                position=position,
            )
            for position, (name, sku, price_cents, stock) in enumerate(product["variants"])
        ]
        db.create_product(
            ProductInput(
                name=product["name"],
                slug=product["name"],
                base_sku=base_sku,
                description=product["description"],
                category_label=categories[category_code],
                featured=bool(product.get("featured", False)),
                published=True,
                variants=variants,
            )
        )
