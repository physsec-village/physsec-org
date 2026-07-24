"""SQLite persistence for catalog, checkout, inventory, and orders.

All inventory transitions use ``BEGIN IMMEDIATE``.  Stripe/network operations
must happen outside these transactions and be retried with the checkout ID as
their provider idempotency key.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import ProductInput, slugify

DB_PATH = Path(os.getenv("STORE_DB_PATH", "data/store.db"))
MEDIA_DIR = DB_PATH.parent / "media"
SCHEMA_VERSION = 1


class StoreError(RuntimeError):
    pass


class CartUnavailable(StoreError):
    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__("Some cart items are unavailable.")
        self.problems = problems


class CheckoutConflict(StoreError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp(value: datetime | None) -> str:
    value = value or datetime.now(UTC)
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


@contextmanager
def connection(
    db_path: str | Path | None = None, *, write: bool = False
) -> Iterator[sqlite3.Connection]:
    """Open a configured connection; callers explicitly initialize storage."""
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if write:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("BEGIN")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> None:
    """Create the parent directory and apply every pending schema migration."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        for version, sql in _MIGRATIONS:
            if version in applied:
                continue
            try:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{sql}\n"
                    "INSERT INTO schema_migrations(version, applied_at) "
                    f"VALUES({version}, '{utc_now()}');\n"
                    "COMMIT;"
                )
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()


_MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE categories(
            code TEXT PRIMARY KEY,
            label TEXT NOT NULL
        );
        CREATE TABLE products(
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            base_sku TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category_code TEXT NOT NULL REFERENCES categories(code),
            featured INTEGER NOT NULL DEFAULT 0 CHECK(featured IN (0,1)),
            published INTEGER NOT NULL DEFAULT 1 CHECK(published IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE variants(
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
            sku TEXT UNIQUE NOT NULL,
            upc TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
            stock_on_hand INTEGER NOT NULL DEFAULT 0 CHECK(stock_on_hand >= 0),
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE product_images(
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            alt TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE checkouts(
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN
                ('creating','open','paid','expired','failed','canceled')),
            stripe_session_id TEXT UNIQUE,
            stripe_payment_intent_id TEXT,
            currency TEXT NOT NULL,
            subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            completed_at TEXT,
            failure_code TEXT,
            version INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE checkout_items(
            checkout_id TEXT NOT NULL REFERENCES checkouts(id) ON DELETE RESTRICT,
            variant_id INTEGER NOT NULL REFERENCES variants(id) ON DELETE RESTRICT,
            sku TEXT NOT NULL,
            product_name TEXT NOT NULL,
            variant_name TEXT NOT NULL DEFAULT '',
            unit_amount_cents INTEGER NOT NULL CHECK(unit_amount_cents >= 0),
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            PRIMARY KEY(checkout_id, variant_id)
        );
        CREATE TABLE inventory_reservations(
            id INTEGER PRIMARY KEY,
            checkout_id TEXT NOT NULL REFERENCES checkouts(id) ON DELETE RESTRICT,
            variant_id INTEGER NOT NULL REFERENCES variants(id) ON DELETE RESTRICT,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            state TEXT NOT NULL CHECK(state IN ('active','consumed','released')),
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finalized_at TEXT,
            UNIQUE(checkout_id, variant_id)
        );
        CREATE TABLE stripe_events(
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            stripe_object_id TEXT,
            stripe_created_at INTEGER,
            payload_sha256 TEXT,
            state TEXT NOT NULL CHECK(state IN
                ('received','processed','ignored','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            received_at TEXT NOT NULL,
            processed_at TEXT,
            last_error_code TEXT,
            last_error_detail TEXT
        );
        CREATE TABLE orders(
            id TEXT PRIMARY KEY,
            checkout_id TEXT UNIQUE NOT NULL REFERENCES checkouts(id),
            stripe_session_id TEXT UNIQUE NOT NULL,
            payment_intent_id TEXT UNIQUE,
            email TEXT,
            shipping_json TEXT,
            currency TEXT NOT NULL,
            amount_subtotal_cents INTEGER NOT NULL CHECK(amount_subtotal_cents >= 0),
            amount_shipping_cents INTEGER NOT NULL DEFAULT 0 CHECK(amount_shipping_cents >= 0),
            amount_tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(amount_tax_cents >= 0),
            amount_total_cents INTEGER NOT NULL CHECK(amount_total_cents >= 0),
            amount_refunded_cents INTEGER NOT NULL DEFAULT 0
                CHECK(amount_refunded_cents >= 0 AND amount_refunded_cents <= amount_total_cents),
            payment_state TEXT NOT NULL CHECK(payment_state IN
                ('pending','paid','failed','canceled')),
            fulfillment_state TEXT NOT NULL CHECK(fulfillment_state IN
                ('unfulfilled','processing','shipped','canceled')),
            review_state TEXT NOT NULL CHECK(review_state IN ('clear','needs_review')),
            review_reason TEXT,
            refund_state TEXT NOT NULL CHECK(refund_state IN ('none','partial','full')),
            created_at TEXT NOT NULL,
            paid_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE order_items(
            id INTEGER PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
            sku TEXT NOT NULL,
            product_name TEXT NOT NULL,
            variant_name TEXT NOT NULL DEFAULT '',
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_amount_cents INTEGER NOT NULL CHECK(unit_amount_cents >= 0)
        );
        CREATE INDEX idx_products_public ON products(published, featured);
        CREATE INDEX idx_variants_product ON variants(product_id, position);
        CREATE INDEX idx_images_product ON product_images(product_id, position);
        CREATE INDEX idx_reservations_active
            ON inventory_reservations(variant_id, expires_at)
            WHERE state = 'active';
        CREATE INDEX idx_checkouts_expiry ON checkouts(status, expires_at);
        CREATE INDEX idx_orders_payment_intent ON orders(payment_intent_id);
        CREATE INDEX idx_order_items_order ON order_items(order_id);
        """,
    )
]


def readiness(db_path: str | Path | None = None) -> dict[str, Any]:
    try:
        with connection(db_path) as conn:
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0]
            ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        return {"ready": ok and version == SCHEMA_VERSION, "schema_version": version}
    except sqlite3.Error as exc:
        return {"ready": False, "error": type(exc).__name__}


def products_count(db_path: str | Path | None = None) -> int:
    with connection(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])


def _available_sql(alias: str = "v") -> str:
    return (
        f"{alias}.stock_on_hand - COALESCE(("
        "SELECT SUM(r.quantity) FROM inventory_reservations r "
        f"WHERE r.variant_id={alias}.id AND r.state='active'),0)"
    )


def _hydrate_products(
    conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]
) -> list[dict[str, Any]]:
    products = [dict(row) for row in rows]
    for product in products:
        variants = [
            dict(row)
            for row in conn.execute(
                f"SELECT v.*, {_available_sql()} AS available_stock "
                "FROM variants v WHERE product_id=? ORDER BY position,id",
                (product["id"],),
            )
        ]
        images = [
            {**dict(row), "url": f"/media/{row['filename']}"}
            for row in conn.execute(
                "SELECT * FROM product_images WHERE product_id=? ORDER BY position,id",
                (product["id"],),
            )
        ]
        prices = [int(v["price_cents"]) for v in variants]
        product.update(
            variants=variants,
            images=images,
            primary_image=images[0] if images else None,
            variant_count=len(variants),
            total_stock=sum(max(0, int(v["available_stock"])) for v in variants),
            all_sold_out=bool(variants)
            and all(int(v["available_stock"]) <= 0 for v in variants),
            min_price_cents=min(prices, default=0),
            max_price_cents=max(prices, default=0),
            price_cents=prices[0] if prices else 0,
            price_varies=len(set(prices)) > 1,
        )
    return products


def get_published_products(
    featured: bool | None = None, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    clause, params = "", []
    if featured is not None:
        clause, params = " AND p.featured=?", [int(featured)]
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT p.*,COALESCE(c.label,p.category_code) category_label "
            "FROM products p LEFT JOIN categories c ON c.code=p.category_code "
            f"WHERE p.published=1{clause} ORDER BY p.featured DESC,p.name",
            params,
        ).fetchall()
        return _hydrate_products(conn, rows)


def get_product_by_slug(
    slug: str, published_only: bool = True, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    published = " AND p.published=1" if published_only else ""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT p.*,COALESCE(c.label,p.category_code) category_label "
            "FROM products p LEFT JOIN categories c ON c.code=p.category_code "
            f"WHERE p.slug=?{published}",
            (slug,),
        ).fetchone()
        return _hydrate_products(conn, [row])[0] if row else None


def get_product_by_id(
    product_id: int | str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT p.*,COALESCE(c.label,p.category_code) category_label "
            "FROM products p LEFT JOIN categories c ON c.code=p.category_code "
            "WHERE p.id=? OR p.base_sku=?",
            (product_id, str(product_id).upper()),
        ).fetchone()
        return _hydrate_products(conn, [row])[0] if row else None


def catalog_json(db_path: str | Path | None = None) -> dict[str, Any]:
    """Return a SKU-first catalog safe to embed in storefront pages."""
    result: dict[str, Any] = {}
    for product in get_published_products(db_path=db_path):
        result[product["base_sku"]] = {
            "name": product["name"],
            "price_cents": product["price_cents"],
            "variants": [
                {
                    "sku": v["sku"],
                    "code": v["sku"].split("-")[-1]
                    if v["sku"] != product["base_sku"]
                    else "_",
                    "label": v["name"],
                    "price_cents": v["price_cents"],
                    "available_stock": max(0, v["available_stock"]),
                }
                for v in product["variants"]
            ],
        }
    return result


def normalize_cart(
    items: Sequence[Mapping[str, Any]], db_path: str | Path | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested: dict[str, int] = {}
    problems: list[dict[str, Any]] = []
    for raw in items:
        sku = str(raw.get("sku", "")).strip().upper()
        try:
            qty = int(raw.get("qty", 0))
        except TypeError, ValueError:
            qty = 0
        if not sku or qty < 1 or qty > 99:
            problems.append({"sku": sku, "reason": "quantity"})
            continue
        total = requested.get(sku, 0) + qty
        if total > 99:
            problems.append({"sku": sku, "reason": "quantity"})
            continue
        requested[sku] = total
    if len(requested) > 90:
        return [], [{"sku": "", "reason": "too_many_distinct_items"}]
    if not requested:
        return [], problems
    with connection(db_path) as conn:
        rows = _cart_rows(conn, requested)
    found = {row["sku"] for row in rows}
    normalized = []
    for row in rows:
        item = dict(row)
        item["qty"] = requested[item["sku"]]
        if item["qty"] > int(item["available_stock"]):
            problems.append(
                {
                    "sku": item["sku"],
                    "reason": "stock",
                    "available_stock": max(0, item["available_stock"]),
                }
            )
        normalized.append(item)
    problems.extend(
        {"sku": sku, "reason": "unavailable"} for sku in requested if sku not in found
    )
    return normalized, problems


def _cart_rows(
    conn: sqlite3.Connection, requested: Mapping[str, int]
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in requested)
    return conn.execute(
        f"SELECT v.id variant_id,v.sku,v.name variant_name,v.price_cents,"
        f"{_available_sql()} available_stock,p.name product_name,p.slug,"
        "p.base_sku FROM variants v JOIN products p ON p.id=v.product_id "
        f"WHERE p.published=1 AND v.sku IN ({placeholders})",
        tuple(requested),
    ).fetchall()


def reserve_checkout(
    items: Sequence[Mapping[str, Any]],
    *,
    currency: str = "usd",
    ttl_minutes: int = 30,
    checkout_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and reserve an entire cart in one serialized transaction."""
    if not 30 <= ttl_minutes <= 1440:
        raise ValueError(
            "Reservation lifetime must be between 30 minutes and 24 hours."
        )
    requested: dict[str, int] = {}
    for raw in items:
        sku = str(raw.get("sku", "")).strip().upper()
        try:
            qty = int(raw.get("qty", 0))
        except TypeError, ValueError:
            qty = 0
        if not sku or not 1 <= qty <= 99:
            raise CartUnavailable([{"sku": sku, "reason": "quantity"}])
        requested[sku] = requested.get(sku, 0) + qty
    if (
        not requested
        or len(requested) > 90
        or any(qty > 99 for qty in requested.values())
    ):
        raise CartUnavailable([{"sku": "", "reason": "cart_size"}])
    now_dt = datetime.now(UTC)
    created_at = _timestamp(now_dt)
    expires_at = _timestamp(now_dt + timedelta(minutes=ttl_minutes))
    checkout_id = checkout_id or uuid.uuid4().hex
    with connection(db_path, write=True) as conn:
        rows = _cart_rows(conn, requested)
        by_sku = {row["sku"]: row for row in rows}
        problems = []
        for sku, qty in requested.items():
            row = by_sku.get(sku)
            if row is None:
                problems.append({"sku": sku, "reason": "unavailable"})
            elif qty > int(row["available_stock"]):
                problems.append(
                    {
                        "sku": sku,
                        "reason": "stock",
                        "available_stock": max(0, int(row["available_stock"])),
                    }
                )
        if problems:
            raise CartUnavailable(problems)
        subtotal = sum(int(by_sku[s]["price_cents"]) * q for s, q in requested.items())
        conn.execute(
            "INSERT INTO checkouts(id,status,currency,subtotal_cents,created_at,expires_at) "
            "VALUES(?,'creating',?,?,?,?)",
            (checkout_id, currency.lower(), subtotal, created_at, expires_at),
        )
        for sku, qty in requested.items():
            row = by_sku[sku]
            conn.execute(
                "INSERT INTO checkout_items VALUES(?,?,?,?,?,?,?)",
                (
                    checkout_id,
                    row["variant_id"],
                    sku,
                    row["product_name"],
                    row["variant_name"],
                    row["price_cents"],
                    qty,
                ),
            )
            conn.execute(
                "INSERT INTO inventory_reservations("
                "checkout_id,variant_id,quantity,state,expires_at,created_at) "
                "VALUES(?,?,?,'active',?,?)",
                (checkout_id, row["variant_id"], qty, expires_at, created_at),
            )
    return get_checkout(checkout_id, db_path=db_path) or {}


def get_checkout(
    checkout_id: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM checkouts WHERE id=?", (checkout_id,)
        ).fetchone()
        if not row:
            return None
        checkout = dict(row)
        checkout["items"] = [
            dict(item)
            for item in conn.execute(
                "SELECT sku,product_name,variant_name,unit_amount_cents,quantity "
                "FROM checkout_items WHERE checkout_id=? ORDER BY sku",
                (checkout_id,),
            )
        ]
        return checkout


def attach_stripe_session(
    checkout_id: str,
    session_id: str,
    *,
    expires_at: datetime | None = None,
    db_path: str | Path | None = None,
) -> None:
    with connection(db_path, write=True) as conn:
        values: list[Any] = [session_id]
        expiry_sql = ""
        if expires_at:
            expiry_sql = ",expires_at=?"
            values.append(_timestamp(expires_at))
        values.append(checkout_id)
        result = conn.execute(
            f"UPDATE checkouts SET stripe_session_id=?,status='open',version=version+1"
            f"{expiry_sql} WHERE id=? AND status IN ('creating','open')",
            values,
        )
        if result.rowcount != 1:
            raise CheckoutConflict("Checkout cannot accept a Stripe session.")
        if expires_at:
            conn.execute(
                "UPDATE inventory_reservations SET expires_at=? "
                "WHERE checkout_id=? AND state='active'",
                (_timestamp(expires_at), checkout_id),
            )


def mark_provider_failure(
    checkout_id: str,
    failure_code: str,
    db_path: str | Path | None = None,
) -> bool:
    with connection(db_path, write=True) as conn:
        changed = conn.execute(
            "UPDATE checkouts SET status='failed',failure_code=?,version=version+1 "
            "WHERE id=? AND status IN ('creating','open')",
            (failure_code[:100], checkout_id),
        ).rowcount
        if changed:
            _release(conn, checkout_id)
        return bool(changed)


def cleanup_expired_reservations(
    *, limit: int = 100, now: datetime | None = None, db_path: str | Path | None = None
) -> int:
    with connection(db_path, write=True) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM checkouts WHERE status IN ('creating','open') "
                "AND expires_at<=? ORDER BY expires_at LIMIT ?",
                (_timestamp(now), max(1, min(limit, 1000))),
            )
        ]
        for checkout_id in ids:
            conn.execute(
                "UPDATE checkouts SET status='expired',version=version+1 WHERE id=?",
                (checkout_id,),
            )
            _release(conn, checkout_id)
        return len(ids)


def _release(conn: sqlite3.Connection, checkout_id: str) -> None:
    conn.execute(
        "UPDATE inventory_reservations SET state='released',finalized_at=? "
        "WHERE checkout_id=? AND state='active'",
        (utc_now(), checkout_id),
    )


def _event_begin(
    conn: sqlite3.Connection,
    event_id: str,
    event_type: str,
    object_id: str | None,
    *,
    stripe_created_at: int | None = None,
    payload: bytes | None = None,
) -> bool:
    existing = conn.execute(
        "SELECT state FROM stripe_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if existing and existing["state"] in {"processed", "ignored"}:
        return False
    digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
    conn.execute(
        "INSERT INTO stripe_events(event_id,event_type,stripe_object_id,"
        "stripe_created_at,payload_sha256,state,attempts,received_at) "
        "VALUES(?,?,?,?,?,'received',1,?) "
        "ON CONFLICT(event_id) DO UPDATE SET attempts=attempts+1,state='received',"
        "last_error_code=NULL,last_error_detail=NULL",
        (event_id, event_type, object_id, stripe_created_at, digest, utc_now()),
    )
    return True


def _event_done(
    conn: sqlite3.Connection, event_id: str, state: str = "processed"
) -> None:
    conn.execute(
        "UPDATE stripe_events SET state=?,processed_at=? WHERE event_id=?",
        (state, utc_now(), event_id),
    )


def record_event_failure(
    event_id: str,
    event_type: str,
    error_code: str,
    detail: str = "",
    *,
    object_id: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Persist a bounded, PII-free failure after a domain transaction rolls back."""
    with connection(db_path, write=True) as conn:
        if not _event_begin(conn, event_id, event_type, object_id):
            return
        conn.execute(
            "UPDATE stripe_events SET state='failed',last_error_code=?,"
            "last_error_detail=? WHERE event_id=? "
            "AND state NOT IN ('processed','ignored')",
            (error_code[:100], detail[:500], event_id),
        )


def process_ignored_event(
    event_id: str,
    event_type: str,
    *,
    object_id: str | None = None,
    stripe_created_at: int | None = None,
    payload: bytes | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Record an irrelevant or unpaid signed event without retaining its body."""
    with connection(db_path, write=True) as conn:
        if not _event_begin(
            conn,
            event_id,
            event_type,
            object_id,
            stripe_created_at=stripe_created_at,
            payload=payload,
        ):
            return "duplicate"
        _event_done(conn, event_id, "ignored")
        return "ignored"


def process_paid_event(
    event_id: str,
    session: Mapping[str, Any],
    *,
    event_type: str = "checkout.session.completed",
    stripe_created_at: int | None = None,
    payload: bytes | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Consume reservations and create an order exactly once."""
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    checkout_id = str(metadata.get("checkout_id") or metadata.get("cart_id") or "")
    if not checkout_id:
        checkout_id = str(session.get("client_reference_id") or "")
    if not session_id or not checkout_id:
        raise CheckoutConflict("Paid event lacks checkout identity.")
    with connection(db_path, write=True) as conn:
        if not _event_begin(
            conn,
            event_id,
            event_type,
            session_id,
            stripe_created_at=stripe_created_at,
            payload=payload,
        ):
            return "duplicate"
        checkout = conn.execute(
            "SELECT * FROM checkouts WHERE id=?", (checkout_id,)
        ).fetchone()
        if checkout is None:
            raise CheckoutConflict("Paid checkout is missing.")
        if checkout["status"] == "paid":
            _event_done(conn, event_id)
            return "duplicate"
        if checkout["status"] not in {"creating", "open"}:
            raise CheckoutConflict(f"Paid checkout is {checkout['status']}.")
        if checkout["stripe_session_id"] not in {None, session_id}:
            raise CheckoutConflict("Stripe session does not match checkout.")
        currency = str(session.get("currency") or "").lower()
        subtotal = int(session.get("amount_subtotal") or 0)
        if session.get("payment_status") != "paid":
            raise CheckoutConflict("Stripe session is not paid.")
        if currency != checkout["currency"] or subtotal != checkout["subtotal_cents"]:
            raise CheckoutConflict("Stripe totals do not match checkout snapshot.")
        reservations = conn.execute(
            "SELECT * FROM inventory_reservations WHERE checkout_id=?",
            (checkout_id,),
        ).fetchall()
        if not reservations or any(row["state"] != "active" for row in reservations):
            raise CheckoutConflict("Inventory reservation is not active.")
        for reservation in reservations:
            changed = conn.execute(
                "UPDATE variants SET stock_on_hand=stock_on_hand-? "
                "WHERE id=? AND stock_on_hand>=?",
                (
                    reservation["quantity"],
                    reservation["variant_id"],
                    reservation["quantity"],
                ),
            ).rowcount
            if changed != 1:
                raise CheckoutConflict("Reserved inventory cannot be consumed.")
        now = utc_now()
        conn.execute(
            "UPDATE inventory_reservations SET state='consumed',finalized_at=? "
            "WHERE checkout_id=? AND state='active'",
            (now, checkout_id),
        )
        payment_intent = _object_id(session.get("payment_intent"))
        order_id = uuid.uuid4().hex
        total_details = session.get("total_details") or {}
        shipping = _shipping(session)
        customer = session.get("customer_details") or {}
        total = int(session.get("amount_total") or subtotal)
        if total < subtotal:
            raise CheckoutConflict("Stripe total is less than the checkout subtotal.")
        conn.execute(
            "INSERT INTO orders(id,checkout_id,stripe_session_id,payment_intent_id,"
            "email,shipping_json,currency,amount_subtotal_cents,"
            "amount_shipping_cents,amount_tax_cents,amount_total_cents,"
            "payment_state,fulfillment_state,review_state,refund_state,"
            "created_at,paid_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,'paid','unfulfilled','clear','none',?,?,?)",
            (
                order_id,
                checkout_id,
                session_id,
                payment_intent,
                customer.get("email") if isinstance(customer, Mapping) else None,
                json.dumps(shipping, separators=(",", ":")) if shipping else None,
                currency,
                subtotal,
                int(total_details.get("amount_shipping") or 0),
                int(total_details.get("amount_tax") or 0),
                total,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO order_items(order_id,sku,product_name,variant_name,"
            "quantity,unit_amount_cents) SELECT ?,sku,product_name,variant_name,"
            "quantity,unit_amount_cents FROM checkout_items WHERE checkout_id=?",
            (order_id, checkout_id),
        )
        conn.execute(
            "UPDATE checkouts SET status='paid',stripe_session_id=?,"
            "stripe_payment_intent_id=?,completed_at=?,version=version+1 WHERE id=?",
            (session_id, payment_intent, now, checkout_id),
        )
        _event_done(conn, event_id)
        return order_id


def process_expired_event(
    event_id: str,
    session: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
) -> str:
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    checkout_id = str(metadata.get("checkout_id") or metadata.get("cart_id") or "")
    checkout_id = checkout_id or str(session.get("client_reference_id") or "")
    with connection(db_path, write=True) as conn:
        if not _event_begin(conn, event_id, "checkout.session.expired", session_id):
            return "duplicate"
        row = conn.execute(
            "SELECT status,stripe_session_id FROM checkouts WHERE id=?", (checkout_id,)
        ).fetchone()
        if row is None:
            raise CheckoutConflict("Expired checkout is missing.")
        if row["stripe_session_id"] not in {None, session_id}:
            raise CheckoutConflict("Stripe session does not match checkout.")
        if row["status"] in {"creating", "open"}:
            conn.execute(
                "UPDATE checkouts SET status='expired',stripe_session_id=?,"
                "version=version+1 WHERE id=?",
                (session_id, checkout_id),
            )
            _release(conn, checkout_id)
        _event_done(conn, event_id)
        return "expired" if row["status"] in {"creating", "open"} else row["status"]


def process_refund_event(
    event_id: str,
    charge: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
) -> str:
    payment_intent = _object_id(charge.get("payment_intent"))
    if not payment_intent:
        raise CheckoutConflict("Refund lacks payment intent.")
    with connection(db_path, write=True) as conn:
        if not _event_begin(
            conn, event_id, "charge.refunded", str(charge.get("id") or "")
        ):
            return "duplicate"
        order = conn.execute(
            "SELECT id,amount_total_cents,amount_refunded_cents FROM orders "
            "WHERE payment_intent_id=?",
            (payment_intent,),
        ).fetchone()
        if not order:
            raise CheckoutConflict("Refund arrived before its order.")
        refunded = max(
            int(order["amount_refunded_cents"]),
            max(0, int(charge.get("amount_refunded") or 0)),
        )
        refunded = min(refunded, int(order["amount_total_cents"]))
        total = int(order["amount_total_cents"])
        state = (
            "full"
            if total > 0 and refunded >= total
            else "partial"
            if refunded
            else "none"
        )
        conn.execute(
            "UPDATE orders SET amount_refunded_cents=?,refund_state=?,updated_at=? "
            "WHERE id=?",
            (refunded, state, utc_now(), order["id"]),
        )
        _event_done(conn, event_id)
        return state


def confirmation_lookup(
    session_id: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT id,payment_state,fulfillment_state,review_state,refund_state,"
            "amount_total_cents,currency,created_at FROM orders "
            "WHERE stripe_session_id=?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def _object_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return str(value.get("id")) if value.get("id") else None
    return getattr(value, "id", None)


def _shipping(session: Mapping[str, Any]) -> Any:
    collected = session.get("collected_information") or {}
    if isinstance(collected, Mapping) and collected.get("shipping_details"):
        return collected["shipping_details"]
    return session.get("shipping_details")


# Product mutation helpers retained for seed/admin integration.  Variants with
# active reservations cannot be destructively replaced.
def create_product(
    product: ProductInput,
    images: list[dict[str, Any]] | None = None,
    db_path: str | Path | None = None,
) -> int:
    now = utc_now()
    with connection(db_path, write=True) as conn:
        conn.execute(
            "INSERT INTO categories(code,label) VALUES(?,?) "
            "ON CONFLICT(code) DO UPDATE SET label=excluded.label "
            "WHERE excluded.label<>excluded.code",
            (product.category_code, product.category_label or product.category_code),
        )
        base = slugify(product.slug)
        slug, suffix = base, 2
        while conn.execute("SELECT 1 FROM products WHERE slug=?", (slug,)).fetchone():
            slug, suffix = f"{base}-{suffix}", suffix + 1
        cursor = conn.execute(
            "INSERT INTO products(slug,name,base_sku,description,category_code,"
            "featured,published,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
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
        product_id = int(cursor.lastrowid)
        for variant in product.variants:
            conn.execute(
                "INSERT INTO variants(product_id,sku,upc,name,price_cents,"
                "stock_on_hand,position) VALUES(?,?,?,?,?,?,?)",
                (
                    product_id,
                    variant.sku,
                    variant.upc,
                    variant.name,
                    variant.price_cents,
                    variant.stock_on_hand,
                    variant.position,
                ),
            )
        for image in images or []:
            conn.execute(
                "INSERT INTO product_images(product_id,filename,alt,position) "
                "VALUES(?,?,?,?)",
                (
                    product_id,
                    image["filename"],
                    image.get("alt", ""),
                    int(image.get("position", 0)),
                ),
            )
        return product_id
