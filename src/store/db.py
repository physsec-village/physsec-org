"""PostgreSQL persistence for catalog, checkout, inventory, and orders.

Inventory transitions lock affected rows in deterministic order. Stripe/network
operations happen outside database transactions and use the durable checkout ID
as their provider idempotency key.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import database_url

MEDIA_DIR = os.getenv("STORE_MEDIA_DIR", "data/media")
SCHEMA_VERSION = 2
_pool: ConnectionPool | None = None


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
def connection(*, write: bool = False) -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection and bound its work to one transaction."""
    del write  # All pooled work is transactional.
    pool = _get_pool()
    with pool.connection(timeout=5) as conn, conn.transaction():
        yield conn


def _configure_connection(conn: psycopg.Connection) -> None:
    conn.execute("SET search_path TO store, public")
    conn.execute("SET statement_timeout TO '10s'")
    conn.execute("SET lock_timeout TO '5s'")
    conn.commit()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            database_url(),
            min_size=1,
            max_size=10,
            timeout=5,
            kwargs={"row_factory": dict_row},
            configure=_configure_connection,
            check=ConnectionPool.check_connection,
            open=False,
        )
        _pool.open(wait=True)
    return _pool


def open_pool() -> None:
    """Open and verify the process-level PostgreSQL connection pool."""
    _get_pool()


def close_pool() -> None:
    """Close the process-level pool during application shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def require_schema() -> None:
    """Fail startup when the versioned store migration is absent."""
    status = readiness()
    if not status["ready"]:
        raise RuntimeError(f"Store database is not ready: {status}")


def readiness() -> dict[str, Any]:
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT version FROM schema_metadata WHERE singleton"
            ).fetchone()
            version = int(row["version"]) if row else 0
            conn.execute("SELECT 1")
        return {"ready": version == SCHEMA_VERSION, "schema_version": version}
    except (psycopg.Error, RuntimeError, ValueError) as exc:
        return {"ready": False, "error": type(exc).__name__}


def _available_sql(alias: str = "v") -> str:
    return (
        f"{alias}.stock_on_hand - COALESCE(("
        "SELECT SUM(r.quantity) FROM inventory_reservations r "
        f"WHERE r.variant_id={alias}.id AND r.state='active'),0)"
    )


def _hydrate_products(
    conn: psycopg.Connection, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    products = [dict(row) for row in rows]
    if not products:
        return products
    product_ids = [product["id"] for product in products]
    variants_by_product: dict[int, list[dict[str, Any]]] = {
        product_id: [] for product_id in product_ids
    }
    for row in conn.execute(
        f"SELECT v.*, {_available_sql()} AS available_stock "
        "FROM variants v WHERE product_id = ANY(%s) "
        "ORDER BY product_id,position,id",
        (product_ids,),
    ):
        variants_by_product[int(row["product_id"])].append(dict(row))
    images_by_product: dict[int, list[dict[str, Any]]] = {
        product_id: [] for product_id in product_ids
    }
    for row in conn.execute(
        "SELECT * FROM product_images WHERE product_id = ANY(%s) "
        "ORDER BY product_id,position,id",
        (product_ids,),
    ):
        image = dict(row)
        images_by_product[int(row["product_id"])].append(image)

    for product in products:
        variants = variants_by_product[product["id"]]
        images = images_by_product[product["id"]]
        prices = [int(v["price_cents"]) for v in variants]
        product.update(
            variants=variants,
            images=images,
            primary_image=images[0] if images else None,
            variant_count=len(variants),
            total_stock=sum(max(0, int(v["available_stock"])) for v in variants),
            all_sold_out=not any(int(v["available_stock"]) > 0 for v in variants),
            min_price_cents=min(prices, default=0),
            max_price_cents=max(prices, default=0),
            price_cents=prices[0] if prices else 0,
            price_varies=len(set(prices)) > 1,
        )
    return products


def get_published_products(featured: bool | None = None) -> list[dict[str, Any]]:
    clause, params = "", []
    if featured is not None:
        clause, params = " AND p.featured=%s", [featured]
    with connection() as conn:
        rows = conn.execute(
            f"SELECT p.* FROM products p WHERE p.published{clause} "
            "ORDER BY p.featured DESC,p.name,p.id",
            params,
        ).fetchall()
        return _hydrate_products(conn, rows)


def get_published_collections() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT c.*,(SELECT COUNT(DISTINCT i.product_id) "
            "FROM collection_groups g JOIN collection_items i ON i.group_id=g.id "
            "JOIN products p ON p.id=i.product_id AND p.published "
            "WHERE g.collection_id=c.id) AS item_count,"
            "(SELECT im.url FROM collection_groups g "
            "JOIN collection_items i ON i.group_id=g.id "
            "JOIN products p ON p.id=i.product_id AND p.published "
            "JOIN product_images im ON im.product_id=p.id "
            "WHERE g.collection_id=c.id "
            "ORDER BY g.position,g.id,i.position,p.id,im.position,im.id LIMIT 1) "
            "AS cover_url FROM collections c WHERE c.published "
            "ORDER BY c.position,c.id"
        )
        return [dict(row) for row in rows]


def get_collection_by_slug(slug: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM collections WHERE slug=%s AND published", (slug,)
        ).fetchone()
        if row is None:
            return None
        collection = dict(row)
        groups = [
            dict(group)
            for group in conn.execute(
                "SELECT * FROM collection_groups WHERE collection_id=%s "
                "ORDER BY position,id",
                (collection["id"],),
            )
        ]
        rows = conn.execute(
            "SELECT p.*,i.group_id FROM collection_groups g "
            "JOIN collection_items i ON i.group_id=g.id "
            "JOIN products p ON p.id=i.product_id AND p.published "
            "WHERE g.collection_id=%s "
            "ORDER BY g.position,g.id,i.position,p.id",
            (collection["id"],),
        ).fetchall()
        by_group = {group["id"]: [] for group in groups}
        for product in _hydrate_products(conn, rows):
            by_group[product.pop("group_id")].append(product)
        for group in groups:
            group["products"] = by_group[group["id"]]
        collection["groups"] = groups
        collection["item_count"] = len({row["id"] for row in rows})
        collection["cover_url"] = next(
            (
                product["primary_image"]["url"]
                for group in groups
                for product in group["products"]
                if product["primary_image"]
            ),
            None,
        )
        return collection


def get_product_by_slug(slug: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE slug=%s AND published", (slug,)
        ).fetchone()
        if row is None:
            return None
        product = _hydrate_products(conn, [row])[0]
        product["memberships"] = [
            dict(membership)
            for membership in conn.execute(
                "SELECT c.id collection_id,c.slug collection_slug,"
                "c.title collection_title,g.id group_id,g.title group_title "
                "FROM collection_items i JOIN collection_groups g ON g.id=i.group_id "
                "JOIN collections c ON c.id=g.collection_id AND c.published "
                "WHERE i.product_id=%s ORDER BY c.position,c.id,g.position,g.id",
                (product["id"],),
            )
        ]
        return product


def search_products(query: str) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    with connection() as conn:
        rows = conn.execute(
            "SELECT p.* FROM products p WHERE p.published AND ("
            "p.name ILIKE %s OR p.description ILIKE %s OR EXISTS("
            "SELECT 1 FROM variants v WHERE v.product_id=p.id "
            "AND (v.name ILIKE %s OR v.sku ILIKE %s))) ORDER BY p.name,p.id",
            (pattern, pattern, pattern, pattern),
        ).fetchall()
        return _hydrate_products(conn, rows)


def get_related_products(product_id: int, limit: int = 4) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "WITH related AS (SELECT other.product_id,"
            "MIN(CASE WHEN other.group_id=own.group_id THEN 0 ELSE 1 END) priority "
            "FROM collection_items own "
            "JOIN collection_groups own_group ON own_group.id=own.group_id "
            "JOIN collections c ON c.id=own_group.collection_id AND c.published "
            "JOIN collection_groups other_group ON other_group.collection_id=c.id "
            "JOIN collection_items other ON other.group_id=other_group.id "
            "WHERE own.product_id=%s AND other.product_id<>%s "
            "GROUP BY other.product_id) "
            "SELECT p.* FROM related r JOIN products p ON p.id=r.product_id "
            "WHERE p.published ORDER BY r.priority,p.name,p.id LIMIT %s",
            (product_id, product_id, max(0, min(limit, 4))),
        ).fetchall()
        return _hydrate_products(conn, rows)


def _requested_cart(
    items: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    requested: dict[int, int] = {}
    problems: list[dict[str, Any]] = []
    for raw in items:
        variant_id = raw.get("variant_id")
        qty = raw.get("qty")
        if type(variant_id) is not int or variant_id < 1:
            problems.append({"variant_id": variant_id, "reason": "unavailable"})
            continue
        if type(qty) is not int or not 1 <= qty <= 99:
            problems.append({"variant_id": variant_id, "reason": "quantity"})
            continue
        total = requested.get(variant_id, 0) + qty
        if total > 99:
            problems.append({"variant_id": variant_id, "reason": "quantity"})
            continue
        requested[variant_id] = total
    if len(requested) > 90:
        return {}, [{"variant_id": None, "reason": "too_many_distinct_items"}]
    return requested, problems


def normalize_cart(
    items: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested, problems = _requested_cart(items)
    if not requested:
        return [], problems
    with connection() as conn:
        rows = _cart_rows(conn, requested)
    found = {row["variant_id"] for row in rows}
    normalized = []
    for row in rows:
        item = dict(row)
        item["qty"] = requested[item["variant_id"]]
        if item["qty"] > int(item["available_stock"]):
            problems.append(
                {
                    "variant_id": item["variant_id"],
                    "reason": "stock",
                    "available_stock": max(0, item["available_stock"]),
                }
            )
        normalized.append(item)
    problems.extend(
        {"variant_id": variant_id, "reason": "unavailable"}
        for variant_id in requested if variant_id not in found
    )
    return normalized, problems


def _cart_rows(
    conn: psycopg.Connection, requested: Mapping[int, int]
) -> list[Mapping[str, Any]]:
    return conn.execute(
        "SELECT v.id variant_id,v.sku,v.name variant_name,v.price_cents,"
        f"{_available_sql()} available_stock,p.name product_name,p.slug,"
        "(SELECT im.url FROM product_images im WHERE im.product_id=p.id "
        "ORDER BY im.position,im.id LIMIT 1) image_url "
        "FROM variants v JOIN products p ON p.id=v.product_id "
        "WHERE p.published AND v.id = ANY(%s) ORDER BY v.id",
        (list(requested),),
    ).fetchall()


def reserve_checkout(
    items: Sequence[Mapping[str, Any]],
    *,
    currency: str = "usd",
    ttl_minutes: int = 35,
) -> dict[str, Any]:
    """Validate and reserve an entire cart in one serialized transaction."""
    if not 31 <= ttl_minutes <= 1440:
        raise ValueError(
            "Reservation lifetime must be between 31 minutes and 24 hours."
        )
    requested, problems = _requested_cart(items)
    if problems:
        raise CartUnavailable(problems)
    if not requested:
        raise CartUnavailable([{"variant_id": None, "reason": "cart_size"}])
    now_dt = datetime.now(UTC)
    created_at = _timestamp(now_dt)
    expires_at = _timestamp(now_dt + timedelta(minutes=ttl_minutes))
    checkout_id = uuid.uuid4().hex
    with connection(write=True) as conn:
        conn.execute(
            "SELECT id FROM variants WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
            (sorted(requested),),
        ).fetchall()
        rows = _cart_rows(conn, requested)
        by_id = {row["variant_id"]: row for row in rows}
        problems = []
        for variant_id, qty in requested.items():
            row = by_id.get(variant_id)
            if row is None:
                problems.append({"variant_id": variant_id, "reason": "unavailable"})
            elif qty > int(row["available_stock"]):
                problems.append(
                    {
                        "variant_id": variant_id,
                        "reason": "stock",
                        "available_stock": max(0, int(row["available_stock"])),
                    }
                )
        if problems:
            raise CartUnavailable(problems)
        subtotal = sum(int(by_id[v]["price_cents"]) * q for v, q in requested.items())
        conn.execute(
            "INSERT INTO checkouts(id,status,currency,subtotal_cents,created_at,expires_at) "
            "VALUES(%s,'creating',%s,%s,%s,%s)",
            (checkout_id, currency.lower(), subtotal, created_at, expires_at),
        )
        for variant_id, qty in requested.items():
            row = by_id[variant_id]
            conn.execute(
                "INSERT INTO checkout_items("
                "checkout_id,variant_id,sku,product_name,variant_name,"
                "unit_amount_cents,quantity) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    checkout_id,
                    variant_id,
                    row["sku"],
                    row["product_name"],
                    row["variant_name"],
                    row["price_cents"],
                    qty,
                ),
            )
            conn.execute(
                "INSERT INTO inventory_reservations("
                "checkout_id,variant_id,quantity,state,expires_at,created_at) "
                "VALUES(%s,%s,%s,'active',%s,%s)",
                (checkout_id, variant_id, qty, expires_at, created_at),
            )
    return get_checkout(checkout_id) or {}


def get_checkout(checkout_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM checkouts WHERE id=%s", (checkout_id,)
        ).fetchone()
        if not row:
            return None
        checkout = dict(row)
        for key in ("created_at", "expires_at", "completed_at"):
            if isinstance(checkout.get(key), datetime):
                checkout[key] = _timestamp(checkout[key])
        checkout["items"] = [
            dict(item)
            for item in conn.execute(
                "SELECT variant_id,sku,product_name,variant_name,unit_amount_cents,quantity "
                "FROM checkout_items WHERE checkout_id=%s ORDER BY variant_id",
                (checkout_id,),
            )
        ]
        return checkout


def attach_stripe_session(
    checkout_id: str,
    session_id: str,
    *,
    expires_at: datetime | None = None,
) -> None:
    with connection(write=True) as conn:
        values: list[Any] = [session_id]
        expiry_sql = ""
        if expires_at:
            expiry_sql = ",expires_at=%s"
            values.append(_timestamp(expires_at))
        values.append(checkout_id)
        result = conn.execute(
            f"UPDATE checkouts SET stripe_session_id=%s,status='open',version=version+1"
            f"{expiry_sql} WHERE id=%s AND status IN ('creating','open')",
            values,
        )
        if result.rowcount != 1:
            raise CheckoutConflict("Checkout cannot accept a Stripe session.")
        if expires_at:
            conn.execute(
                "UPDATE inventory_reservations SET expires_at=%s "
                "WHERE checkout_id=%s AND state='active'",
                (_timestamp(expires_at), checkout_id),
            )


def mark_provider_failure(
    checkout_id: str,
    failure_code: str,
) -> bool:
    with connection(write=True) as conn:
        changed = conn.execute(
            "UPDATE checkouts SET status='failed',failure_code=%s,version=version+1 "
            "WHERE id=%s AND status IN ('creating','open')",
            (failure_code[:100], checkout_id),
        ).rowcount
        if changed:
            _release(conn, checkout_id)
        return bool(changed)


def cleanup_expired_reservations(
    *, limit: int = 100, now: datetime | None = None
) -> int:
    with connection(write=True) as conn:
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM checkouts WHERE status IN ('creating','open') "
                "AND expires_at<=%s ORDER BY expires_at LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (_timestamp(now), max(1, min(limit, 1000))),
            )
        ]
        for checkout_id in ids:
            conn.execute(
                "UPDATE checkouts SET status='expired',version=version+1 WHERE id=%s",
                (checkout_id,),
            )
            _release(conn, checkout_id)
        return len(ids)


def _release(conn: psycopg.Connection, checkout_id: str) -> None:
    conn.execute(
        "UPDATE inventory_reservations SET state='released',finalized_at=%s "
        "WHERE checkout_id=%s AND state='active'",
        (utc_now(), checkout_id),
    )


def _event_begin(
    conn: psycopg.Connection,
    event_id: str,
    event_type: str,
    object_id: str | None,
    *,
    stripe_created_at: int | None = None,
    payload: bytes | None = None,
) -> bool:
    digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
    inserted = conn.execute(
        "INSERT INTO stripe_events(event_id,event_type,stripe_object_id,"
        "stripe_created_at,payload_sha256,state,attempts,received_at) "
        "VALUES(%s,%s,%s,%s,%s,'received',1,%s) "
        "ON CONFLICT(event_id) DO NOTHING RETURNING event_id",
        (event_id, event_type, object_id, stripe_created_at, digest, utc_now()),
    ).fetchone()
    if inserted:
        return True
    existing = conn.execute(
        "SELECT state FROM stripe_events WHERE event_id=%s FOR UPDATE", (event_id,)
    ).fetchone()
    if existing and existing["state"] in {"processed", "ignored"}:
        return False
    conn.execute(
        "UPDATE stripe_events SET attempts=attempts+1,state='received',"
        "last_error_code=NULL,last_error_detail=NULL WHERE event_id=%s",
        (event_id,),
    )
    return True


def _event_done(
    conn: psycopg.Connection, event_id: str, state: str = "processed"
) -> None:
    conn.execute(
        "UPDATE stripe_events SET state=%s,processed_at=%s WHERE event_id=%s",
        (state, utc_now(), event_id),
    )


def record_event_failure(
    event_id: str,
    event_type: str,
    error_code: str,
    detail: str = "",
    *,
    object_id: str | None = None,
) -> None:
    """Persist a bounded, PII-free failure after a domain transaction rolls back."""
    with connection(write=True) as conn:
        if not _event_begin(conn, event_id, event_type, object_id):
            return
        conn.execute(
            "UPDATE stripe_events SET state='failed',last_error_code=%s,"
            "last_error_detail=%s WHERE event_id=%s "
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
) -> str:
    """Record an irrelevant or unpaid signed event without retaining its body."""
    with connection(write=True) as conn:
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
) -> str:
    """Consume reservations and create an order exactly once."""
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    checkout_id = str(metadata.get("checkout_id") or metadata.get("cart_id") or "")
    if not checkout_id:
        checkout_id = str(session.get("client_reference_id") or "")
    if not session_id or not checkout_id:
        raise CheckoutConflict("Paid event lacks checkout identity.")
    with connection(write=True) as conn:
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
            "SELECT * FROM checkouts WHERE id=%s FOR UPDATE", (checkout_id,)
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
            "SELECT * FROM inventory_reservations WHERE checkout_id=%s "
            "ORDER BY variant_id FOR UPDATE",
            (checkout_id,),
        ).fetchall()
        if not reservations or any(row["state"] != "active" for row in reservations):
            raise CheckoutConflict("Inventory reservation is not active.")
        conn.execute(
            "SELECT id FROM variants WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
            ([row["variant_id"] for row in reservations],),
        ).fetchall()
        for reservation in reservations:
            changed = conn.execute(
                "UPDATE variants SET stock_on_hand=stock_on_hand-%s "
                "WHERE id=%s AND stock_on_hand>=%s",
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
            "UPDATE inventory_reservations SET state='consumed',finalized_at=%s "
            "WHERE checkout_id=%s AND state='active'",
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
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'paid','unfulfilled','clear','none',%s,%s,%s)",
            (
                order_id,
                checkout_id,
                session_id,
                payment_intent,
                customer.get("email") if isinstance(customer, Mapping) else None,
                Jsonb(shipping) if shipping else None,
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
            "INSERT INTO order_items(order_id,variant_id,sku,product_name,variant_name,"
            "quantity,unit_amount_cents) SELECT %s,variant_id,sku,product_name,variant_name,"
            "quantity,unit_amount_cents FROM checkout_items WHERE checkout_id=%s",
            (order_id, checkout_id),
        )
        conn.execute(
            "UPDATE checkouts SET status='paid',stripe_session_id=%s,"
            "stripe_payment_intent_id=%s,completed_at=%s,version=version+1 WHERE id=%s",
            (session_id, payment_intent, now, checkout_id),
        )
        _event_done(conn, event_id)
        return order_id


def process_expired_event(
    event_id: str,
    session: Mapping[str, Any],
) -> str:
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    checkout_id = str(metadata.get("checkout_id") or metadata.get("cart_id") or "")
    checkout_id = checkout_id or str(session.get("client_reference_id") or "")
    with connection(write=True) as conn:
        if not _event_begin(conn, event_id, "checkout.session.expired", session_id):
            return "duplicate"
        row = conn.execute(
            "SELECT status,stripe_session_id FROM checkouts WHERE id=%s FOR UPDATE",
            (checkout_id,),
        ).fetchone()
        if row is None:
            raise CheckoutConflict("Expired checkout is missing.")
        if row["stripe_session_id"] not in {None, session_id}:
            raise CheckoutConflict("Stripe session does not match checkout.")
        if row["status"] in {"creating", "open"}:
            conn.execute(
                "UPDATE checkouts SET status='expired',stripe_session_id=%s,"
                "version=version+1 WHERE id=%s",
                (session_id, checkout_id),
            )
            _release(conn, checkout_id)
        _event_done(conn, event_id)
        return "expired" if row["status"] in {"creating", "open"} else row["status"]


def process_refund_event(
    event_id: str,
    charge: Mapping[str, Any],
) -> str:
    payment_intent = _object_id(charge.get("payment_intent"))
    if not payment_intent:
        raise CheckoutConflict("Refund lacks payment intent.")
    with connection(write=True) as conn:
        if not _event_begin(
            conn, event_id, "charge.refunded", str(charge.get("id") or "")
        ):
            return "duplicate"
        order = conn.execute(
            "SELECT id,amount_total_cents,amount_refunded_cents FROM orders "
            "WHERE payment_intent_id=%s FOR UPDATE",
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
            "UPDATE orders SET amount_refunded_cents=%s,refund_state=%s,updated_at=%s "
            "WHERE id=%s",
            (refunded, state, utc_now(), order["id"]),
        )
        _event_done(conn, event_id)
        return state


def confirmation_lookup(session_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id,payment_state,fulfillment_state,review_state,refund_state,"
            "amount_total_cents,currency,created_at FROM orders "
            "WHERE stripe_session_id=%s",
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
