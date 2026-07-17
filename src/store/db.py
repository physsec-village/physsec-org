from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .models import ProductInput, category_code_from_sku, slugify

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "store.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                base_sku TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category_code TEXT NOT NULL,
                featured INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS variants(
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                sku TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                position INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS product_images(
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                alt TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS categories(
                code TEXT PRIMARY KEY,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkout_carts(
                id TEXT PRIMARY KEY,
                cart_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY,
                stripe_session_id TEXT UNIQUE NOT NULL,
                payment_intent TEXT,
                email TEXT,
                amount_subtotal_cents INTEGER,
                amount_shipping_cents INTEGER,
                amount_tax_cents INTEGER,
                amount_total_cents INTEGER,
                currency TEXT,
                shipping_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_items(
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                variant_name TEXT NOT NULL DEFAULT '',
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_amount_cents INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_variants_product_position
                ON variants(product_id, position);
            CREATE INDEX IF NOT EXISTS idx_product_images_product_position
                ON product_images(product_id, position);
            CREATE INDEX IF NOT EXISTS idx_products_published_featured
                ON products(published, featured);
            CREATE INDEX IF NOT EXISTS idx_order_items_order
                ON order_items(order_id);
            """
        )


def products_count() -> int:
    with connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM products").fetchone()
        return int(row["count"])


def list_categories() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT code, label FROM categories ORDER BY label").fetchall()
        return [dict(row) for row in rows]


def upsert_category(code: str, label: str) -> None:
    label = (label or code).strip() or code
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO categories(code, label) VALUES(?, ?)
            ON CONFLICT(code) DO UPDATE SET label = excluded.label
            """,
            (code, label),
        )


def unique_slug(seed: str, product_id: int | None = None) -> str:
    base = slugify(seed)
    slug = base
    suffix = 2
    with connection() as conn:
        while True:
            if product_id is None:
                row = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM products WHERE slug = ? AND id != ?",
                    (slug, product_id),
                ).fetchone()
            if row is None:
                return slug
            slug = f"{base}-{suffix}"
            suffix += 1


def create_product(product: ProductInput, images: list[dict[str, Any]] | None = None) -> int:
    now = utc_now()
    slug = unique_slug(product.slug)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO categories(code, label) VALUES(?, ?)
            ON CONFLICT(code) DO UPDATE SET label = excluded.label
            """,
            (product.category_code, product.category_label or product.category_code),
        )
        cur = conn.execute(
            """
            INSERT INTO products(
                slug, name, base_sku, description, category_code,
                featured, published, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                product.name,
                product.base_sku,
                product.description,
                product.category_code,
                int(product.featured),
                int(product.published),
                now,
                now,
            ),
        )
        product_id = int(cur.lastrowid)
        _insert_variants(conn, product_id, product.variants)
        _insert_images(conn, product_id, images or [])
        return product_id


def update_product(
    product_id: int,
    product: ProductInput,
    existing_images: list[dict[str, Any]],
    delete_image_ids: Iterable[int],
    new_images: list[dict[str, Any]] | None = None,
) -> None:
    now = utc_now()
    slug = unique_slug(product.slug, product_id)
    delete_ids = [int(image_id) for image_id in delete_image_ids]
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO categories(code, label) VALUES(?, ?)
            ON CONFLICT(code) DO UPDATE SET label = excluded.label
            """,
            (product.category_code, product.category_label or product.category_code),
        )
        conn.execute(
            """
            UPDATE products
            SET slug = ?, name = ?, base_sku = ?, description = ?, category_code = ?,
                featured = ?, published = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                slug,
                product.name,
                product.base_sku,
                product.description,
                product.category_code,
                int(product.featured),
                int(product.published),
                now,
                product_id,
            ),
        )
        conn.execute("DELETE FROM variants WHERE product_id = ?", (product_id,))
        _insert_variants(conn, product_id, product.variants)
        for image in existing_images:
            if int(image["id"]) in delete_ids:
                continue
            conn.execute(
                """
                UPDATE product_images SET alt = ?, position = ?
                WHERE id = ? AND product_id = ?
                """,
                (image.get("alt", ""), int(image.get("position", 0)), int(image["id"]), product_id),
            )
        if delete_ids:
            placeholders = ",".join("?" for _ in delete_ids)
            conn.execute(
                f"DELETE FROM product_images WHERE product_id = ? AND id IN ({placeholders})",
                (product_id, *delete_ids),
            )
        _insert_images(conn, product_id, new_images or [])


def _insert_variants(conn: sqlite3.Connection, product_id: int, variants: Iterable[Any]) -> None:
    for variant in variants:
        conn.execute(
            """
            INSERT INTO variants(product_id, sku, name, price_cents, stock, position)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                variant.sku,
                variant.name.strip(),
                int(variant.price_cents),
                int(variant.stock),
                int(variant.position),
            ),
        )


def _insert_images(conn: sqlite3.Connection, product_id: int, images: list[dict[str, Any]]) -> None:
    for image in images:
        conn.execute(
            """
            INSERT INTO product_images(product_id, filename, alt, position)
            VALUES(?, ?, ?, ?)
            """,
            (product_id, image["filename"], image.get("alt", ""), int(image.get("position", 0))),
        )


def delete_product(product_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def set_product_flag(product_id: int, flag: str, enabled: bool) -> None:
    if flag not in {"featured", "published"}:
        raise ValueError("Unsupported product flag.")
    with connection() as conn:
        conn.execute(
            f"UPDATE products SET {flag} = ?, updated_at = ? WHERE id = ?",
            (int(enabled), utc_now(), product_id),
        )


def get_published_products(featured: bool | None = None) -> list[dict[str, Any]]:
    where = "WHERE p.published = 1"
    params: list[Any] = []
    if featured is not None:
        where += " AND p.featured = ?"
        params.append(int(featured))
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, COALESCE(c.label, p.category_code) AS category_label
            FROM products p
            LEFT JOIN categories c ON c.code = p.category_code
            {where}
            ORDER BY p.featured DESC, p.created_at DESC, p.name
            """,
            params,
        ).fetchall()
        return _hydrate_products(conn, rows)


def get_product_by_slug(slug: str, published_only: bool = True) -> dict[str, Any] | None:
    where = "WHERE p.slug = ?"
    params: list[Any] = [slug]
    if published_only:
        where += " AND p.published = 1"
    with connection() as conn:
        row = conn.execute(
            f"""
            SELECT p.*, COALESCE(c.label, p.category_code) AS category_label
            FROM products p
            LEFT JOIN categories c ON c.code = p.category_code
            {where}
            """,
            params,
        ).fetchone()
        products = _hydrate_products(conn, [row] if row else [])
        return products[0] if products else None


def get_product_by_id(product_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT p.*, COALESCE(c.label, p.category_code) AS category_label
            FROM products p
            LEFT JOIN categories c ON c.code = p.category_code
            WHERE p.id = ?
            """,
            (product_id,),
        ).fetchone()
        products = _hydrate_products(conn, [row] if row else [])
        return products[0] if products else None


def list_admin_products() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*, COALESCE(c.label, p.category_code) AS category_label
            FROM products p
            LEFT JOIN categories c ON c.code = p.category_code
            ORDER BY p.updated_at DESC, p.name
            """
        ).fetchall()
        return _hydrate_products(conn, rows)


def get_cart_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    requested = {str(item.get("sku", "")).upper(): int(item.get("qty", 0) or 0) for item in items}
    requested = {sku: qty for sku, qty in requested.items() if sku}
    if not requested:
        return [], []
    with connection() as conn:
        placeholders = ",".join("?" for _ in requested)
        rows = conn.execute(
            f"""
            SELECT v.sku, v.name AS variant_name, v.price_cents, v.stock,
                   p.name AS product_name, p.slug, p.published,
                   p.category_code, COALESCE(c.label, p.category_code) AS category_label,
                   (
                       SELECT filename FROM product_images i
                       WHERE i.product_id = p.id
                       ORDER BY i.position, i.id
                       LIMIT 1
                   ) AS image_filename
            FROM variants v
            JOIN products p ON p.id = v.product_id
            LEFT JOIN categories c ON c.code = p.category_code
            WHERE v.sku IN ({placeholders}) AND p.published = 1
            """,
            tuple(requested.keys()),
        ).fetchall()
        found = {row["sku"] for row in rows}
        normalized: list[dict[str, Any]] = []
        for row in rows:
            qty = max(1, requested[row["sku"]])
            stock = int(row["stock"])
            normalized.append(
                {
                    "sku": row["sku"],
                    "product_name": row["product_name"],
                    "variant_name": row["variant_name"],
                    "slug": row["slug"],
                    "price_cents": int(row["price_cents"]),
                    "stock": stock,
                    "qty": min(qty, stock) if stock > 0 else 0,
                    "image_url": f"/media/{row['image_filename']}" if row["image_filename"] else "",
                    "category_code": row["category_code"],
                    "category_label": row["category_label"],
                }
            )
        removed = sorted(set(requested) - found)
        normalized.sort(key=lambda item: list(requested).index(item["sku"]))
        return normalized, removed


def get_variants_for_checkout(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cart_items, removed = get_cart_items(items)
    problems = [{"sku": sku, "reason": "unavailable"} for sku in removed]
    requested = {str(item.get("sku", "")).upper(): int(item.get("qty", 0) or 0) for item in items}
    checkout_items = []
    for item in cart_items:
        requested_qty = requested.get(item["sku"], 0)
        if requested_qty < 1:
            problems.append({"sku": item["sku"], "reason": "quantity"})
        elif requested_qty > item["stock"]:
            problems.append({"sku": item["sku"], "reason": "stock", "stock": item["stock"]})
        else:
            item["qty"] = requested_qty
            checkout_items.append(item)
    return checkout_items, problems


def create_checkout_cart(items: list[dict[str, Any]]) -> str:
    cart_id = uuid.uuid4().hex
    # Snapshot names/prices at checkout time so the webhook records what was
    # actually sold even if the catalog changes before the event arrives.
    payload = json.dumps(
        [
            {
                "sku": item["sku"],
                "qty": int(item["qty"]),
                "product_name": item.get("product_name", ""),
                "variant_name": item.get("variant_name", ""),
                "price_cents": int(item.get("price_cents", 0)),
            }
            for item in items
        ],
        separators=(",", ":"),
    )
    with connection() as conn:
        conn.execute(
            "INSERT INTO checkout_carts(id, cart_json, created_at) VALUES(?, ?, ?)",
            (cart_id, payload, utc_now()),
        )
    return cart_id


def get_checkout_cart(cart_id: str) -> list[dict[str, Any]] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT cart_json FROM checkout_carts WHERE id = ?",
            (cart_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["cart_json"])


def record_order_from_session(session: Any, cart_items: list[dict[str, Any]]) -> str:
    status = "paid"
    # Newer Checkout API versions expose shipping under
    # collected_information.shipping_details; older ones at the top level.
    collected = _session_value(session, "collected_information") or {}
    shipping = (
        _dict_value(collected, "shipping_details")
        or _session_value(session, "shipping_details")
    )
    shipping_json = (
        json.dumps(shipping, default=str, separators=(",", ":")) if shipping else None
    )

    session_id = _session_value(session, "id")
    payment_intent = _session_value(session, "payment_intent")
    customer_details = _session_value(session, "customer_details") or {}
    email = getattr(customer_details, "email", None) or customer_details.get("email")
    total_details = _session_value(session, "total_details") or {}
    amount_tax = getattr(total_details, "amount_tax", None) or total_details.get("amount_tax")
    amount_shipping = getattr(total_details, "amount_shipping", None) or total_details.get("amount_shipping")

    with connection() as conn:
        existing = conn.execute(
            "SELECT status FROM orders WHERE stripe_session_id = ?",
            (session_id,),
        ).fetchone()
        if existing is not None:
            return existing["status"]

        cur = conn.execute(
            """
            INSERT INTO orders(
                stripe_session_id, payment_intent, email, amount_subtotal_cents,
                amount_shipping_cents, amount_tax_cents, amount_total_cents,
                currency, shipping_json, status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                payment_intent,
                email,
                _session_value(session, "amount_subtotal"),
                amount_shipping,
                amount_tax,
                _session_value(session, "amount_total"),
                _session_value(session, "currency"),
                shipping_json,
                status,
                utc_now(),
            ),
        )
        order_id = int(cur.lastrowid)

        checkout_rows = _cart_rows_for_order(conn, cart_items)
        by_sku = {row["sku"]: row for row in checkout_rows}
        for item in cart_items:
            sku = str(item["sku"]).upper()
            quantity = int(item["qty"])
            # Prefer the checkout-time snapshot; fall back to the current
            # catalog row for carts created before snapshots existed. A
            # snapshot price of 0 is valid and must not trigger the fallback.
            row = by_sku.get(sku) or {}
            snapshot_price = item.get("price_cents")
            conn.execute(
                """
                INSERT INTO order_items(
                    order_id, sku, product_name, variant_name, quantity, unit_amount_cents
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    sku,
                    item.get("product_name") or row.get("product_name") or sku,
                    item.get("variant_name") or row.get("variant_name") or "",
                    quantity,
                    snapshot_price if snapshot_price is not None else row.get("price_cents", 0),
                ),
            )
            result = conn.execute(
                "UPDATE variants SET stock = stock - ? WHERE sku = ? AND stock >= ?",
                (quantity, sku, quantity),
            )
            if result.rowcount == 0:
                conn.execute("UPDATE variants SET stock = 0 WHERE sku = ?", (sku,))
                status = "needs_review"

        if status != "paid":
            conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        return status


def _cart_rows_for_order(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requested = {str(item.get("sku", "")).upper(): int(item.get("qty", 0) or 0) for item in items}
    requested = {sku: qty for sku, qty in requested.items() if sku}
    if not requested:
        return []
    placeholders = ",".join("?" for _ in requested)
    rows = conn.execute(
        f"""
        SELECT v.sku, v.name AS variant_name, v.price_cents, v.stock,
               p.name AS product_name, p.slug, p.category_code,
               COALESCE(c.label, p.category_code) AS category_label,
               (
                   SELECT filename FROM product_images i
                   WHERE i.product_id = p.id
                   ORDER BY i.position, i.id
                   LIMIT 1
               ) AS image_filename
        FROM variants v
        JOIN products p ON p.id = v.product_id
        LEFT JOIN categories c ON c.code = p.category_code
        WHERE v.sku IN ({placeholders})
        """,
        tuple(requested.keys()),
    ).fetchall()
    return [dict(row) for row in rows]


def list_orders() -> list[dict[str, Any]]:
    with connection() as conn:
        order_rows = conn.execute(
            """
            SELECT * FROM orders
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        orders = [dict(row) for row in order_rows]
        if not orders:
            return []
        ids = [order["id"] for order in orders]
        placeholders = ",".join("?" for _ in ids)
        item_rows = conn.execute(
            f"""
            SELECT * FROM order_items
            WHERE order_id IN ({placeholders})
            ORDER BY id
            """,
            ids,
        ).fetchall()
        by_order: dict[int, list[dict[str, Any]]] = {order["id"]: [] for order in orders}
        for row in item_rows:
            by_order[int(row["order_id"])].append(dict(row))
        for order in orders:
            order["items"] = by_order[order["id"]]
        return orders


def _hydrate_products(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    products = [dict(row) for row in rows if row is not None]
    if not products:
        return []
    ids = [product["id"] for product in products]
    placeholders = ",".join("?" for _ in ids)
    variant_rows = conn.execute(
        f"""
        SELECT * FROM variants
        WHERE product_id IN ({placeholders})
        ORDER BY position, id
        """,
        ids,
    ).fetchall()
    image_rows = conn.execute(
        f"""
        SELECT * FROM product_images
        WHERE product_id IN ({placeholders})
        ORDER BY position, id
        """,
        ids,
    ).fetchall()
    by_product: dict[int, dict[str, list[dict[str, Any]]]] = {
        product["id"]: {"variants": [], "images": []} for product in products
    }
    for row in variant_rows:
        by_product[int(row["product_id"])]["variants"].append(dict(row))
    for row in image_rows:
        image = dict(row)
        image["url"] = f"/media/{image['filename']}"
        by_product[int(row["product_id"])]["images"].append(image)
    for product in products:
        product.update(by_product[product["id"]])
        _attach_product_summary(product)
    return products


def _attach_product_summary(product: dict[str, Any]) -> None:
    variants = product.get("variants", [])
    prices = [int(variant["price_cents"]) for variant in variants]
    stocks = [int(variant["stock"]) for variant in variants]
    product["category_label"] = product.get("category_label") or product["category_code"]
    product["variant_count"] = len(variants)
    product["total_stock"] = sum(stocks)
    product["all_sold_out"] = bool(variants) and all(stock <= 0 for stock in stocks)
    product["min_price_cents"] = min(prices) if prices else 0
    product["max_price_cents"] = max(prices) if prices else 0
    product["price_cents"] = prices[0] if prices else 0
    product["price_varies"] = len(set(prices)) > 1
    product["primary_image"] = product["images"][0] if product.get("images") else None


def _session_value(session: Any, key: str) -> Any:
    if isinstance(session, dict):
        return session.get(key)
    return getattr(session, key, None)


def _dict_value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


init_db()
