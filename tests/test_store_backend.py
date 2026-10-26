import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest
import stripe
from fastapi.testclient import TestClient

from src.main import app
from src.store import db, storefront, stripe_client
from src.store import router as store_router
from src.store.config import (
    database_url,
    reservation_minutes,
    store_enabled,
)


def _database(catalog_factory, *, stock: int = 1):
    db.require_schema()
    product = catalog_factory.product(
        slug="rfid-test-tool", name="RFID Test Tool",
        variants=[{"sku": "opaque.inventory/001", "price_cents": 2500, "stock": stock}],
    )
    return product["variants"][0]["id"]


def _paid_session(checkout):
    return {
        "id": "cs_test_paid",
        "client_reference_id": checkout["id"],
        "metadata": {"checkout_id": checkout["id"]},
        "payment_status": "paid",
        "payment_intent": "pi_test_paid",
        "currency": "usd",
        "amount_subtotal": 2500,
        "amount_total": 2500,
        "total_details": {"amount_shipping": 0, "amount_tax": 0},
        "customer_details": {"email": "buyer@example.com"},
    }


def test_schema_and_rfid_catalog(catalog_factory):
    variant_id = _database(catalog_factory)

    assert db.readiness() == {"ready": True, "schema_version": 5}
    product = db.get_published_products()[0]
    assert product["variants"][0]["id"] == variant_id
    assert product["price_cents"] == 2500
    assert product["variants"][0]["available_stock"] == 1


@pytest.mark.parametrize(
    ("name", "value", "reader"),
    [
        ("STORE_RESERVATION_MINUTES", "not-a-number", reservation_minutes),
        ("STORE_RESERVATION_MINUTES", "30", reservation_minutes),
        ("STORE_RESERVATION_MINUTES", "1441", reservation_minutes),
    ],
)
def test_store_numeric_configuration_is_validated(monkeypatch, name, value, reader):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        reader()


def test_store_feature_flag_is_validated(monkeypatch):
    monkeypatch.setenv("STORE_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="STORE_ENABLED"):
        store_enabled()


def test_production_database_requires_tls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/store")

    with pytest.raises(ValueError, match="sslmode=require"):
        database_url()

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://example.test/store?sslmode=require&sslmode=disable",
    )
    with pytest.raises(ValueError, match="sslmode=require"):
        database_url()

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://example.test/store?sslmode=verify-full"
    )
    assert database_url().endswith("sslmode=verify-full")


def test_product_default_variant_prefers_available_stock(catalog_factory):
    product = catalog_factory.product(variants=[
        {"name": "Sold out", "stock": 0}, {"name": "Available", "stock": 2},
    ])
    view = storefront.get_product(product["slug"])
    assert view.default_variant.id == product["variants"][1]["id"]
    assert view.purchasable
    assert not view.sold_out


def test_cart_normalization_caps_duplicate_variant_totals(catalog_factory):
    variant_id = _database(catalog_factory, stock=200)
    normalized, problems = db.normalize_cart(
        [
            {"variant_id": variant_id, "qty": 60},
            {"variant_id": variant_id, "qty": 60},
        ],
    )

    assert normalized[0]["qty"] == 60
    assert problems == [{"variant_id": variant_id, "reason": "quantity"}]


def test_reservation_prevents_overselling_and_expiry_releases(catalog_factory):
    variant_id = _database(catalog_factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(
                db.reserve_checkout,
                [{"variant_id": variant_id, "qty": 1}],
            )
            for _ in range(2)
        ]
    outcomes = []
    for attempt in attempts:
        try:
            outcomes.append(attempt.result()["status"])
        except db.CartUnavailable:
            outcomes.append("unavailable")
    assert sorted(outcomes) == ["creating", "unavailable"]

    assert (
        db.cleanup_expired_reservations(now=datetime.now(UTC) + timedelta(hours=1)) == 1
    )
    replacement = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    assert replacement["status"] == "creating"


def test_paid_event_is_atomic_and_idempotent(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    session = _paid_session(checkout)

    order_id = db.process_paid_event("evt_paid", session)
    assert db.process_paid_event("evt_paid", session) == "duplicate"
    assert (
        db.process_paid_event(
            "evt_async_paid",
            session,
            event_type="checkout.session.async_payment_succeeded",
        )
        == "duplicate"
    )

    confirmation = db.confirmation_lookup("cs_test_paid")
    assert confirmation["id"] == order_id
    assert confirmation["payment_state"] == "paid"
    assert confirmation["fulfillment_state"] == "unfulfilled"
    with db.connection() as conn:
        assert (
            conn.execute("SELECT stock_on_hand FROM variants").fetchone()[
                "stock_on_hand"
            ]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM stripe_events").fetchone()[
                "count"
            ]
            == 2
        )


def test_concurrent_webhook_delivery_creates_one_order(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    session = _paid_session(checkout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(db.process_paid_event, "evt_concurrent", session)
            for _ in range(2)
        ]
    outcomes = [attempt.result() for attempt in attempts]

    assert outcomes.count("duplicate") == 1
    with db.connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
            == 1
        )
        assert conn.execute(
            "SELECT attempts,state FROM stripe_events WHERE event_id='evt_concurrent'"
        ).fetchone() == {"attempts": 1, "state": "processed"}


def test_distinct_paid_events_for_one_checkout_are_idempotent(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    session = _paid_session(checkout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(db.process_paid_event, event_id, session)
            for event_id in ("evt_completed", "evt_async_succeeded")
        ]
    outcomes = [attempt.result() for attempt in attempts]

    assert outcomes.count("duplicate") == 1
    with db.connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT stock_on_hand FROM variants WHERE id=%s", (variant_id,)
            ).fetchone()["stock_on_hand"]
            == 0
        )
        assert {
            row["state"]
            for row in conn.execute(
                "SELECT state FROM stripe_events "
                "WHERE event_id IN ('evt_completed','evt_async_succeeded')"
            )
        } == {"processed"}


def test_payment_and_expiry_cleanup_are_serialized(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")

    def pay():
        try:
            return db.process_paid_event("evt_race", _paid_session(checkout))
        except db.CheckoutConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        payment = pool.submit(pay)
        cleanup = pool.submit(
            db.cleanup_expired_reservations,
            now=datetime.now(UTC) + timedelta(hours=1),
        )
    payment_result, cleanup_count = payment.result(), cleanup.result()

    with db.connection() as conn:
        state = conn.execute(
            "SELECT status FROM checkouts WHERE id=%s", (checkout["id"],)
        ).fetchone()["status"]
        orders = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()[
            "count"
        ]
        reservation = conn.execute(
            "SELECT state FROM inventory_reservations WHERE checkout_id=%s",
            (checkout["id"],),
        ).fetchone()["state"]

    if state == "paid":
        assert payment_result != "conflict"
        assert (cleanup_count, orders, reservation) == (0, 1, "consumed")
    else:
        assert (payment_result, cleanup_count, state, orders, reservation) == (
            "conflict",
            1,
            "expired",
            0,
            "released",
        )


def test_failed_paid_event_rolls_back_then_can_be_recorded(catalog_factory):
    variant_id = _database(catalog_factory)
    missing = {
        "id": "cs_missing",
        "client_reference_id": "missing-checkout",
        "metadata": {"checkout_id": "missing-checkout"},
        "payment_status": "paid",
        "currency": "usd",
        "amount_subtotal": 2500,
    }

    with pytest.raises(db.CheckoutConflict):
        db.process_paid_event("evt_missing", missing)
    db.record_event_failure(
        "evt_missing",
        "checkout.session.completed",
        "checkout_conflict",
        "Paid checkout is missing.",
    )

    with db.connection() as conn:
        event = conn.execute(
            "SELECT state,attempts,last_error_code FROM stripe_events"
        ).fetchone()
    assert dict(event) == {
        "state": "failed",
        "attempts": 1,
        "last_error_code": "checkout_conflict",
    }


def test_paid_event_requires_explicit_payment_status(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    session = _paid_session(checkout)
    session.pop("payment_status")

    with pytest.raises(db.CheckoutConflict, match="not paid"):
        db.process_paid_event("evt_missing_status", session)


def test_refund_state_does_not_overwrite_other_order_states(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    db.process_paid_event("evt_paid", _paid_session(checkout))

    assert (
        db.process_refund_event(
            "evt_refund_partial",
            {
                "id": "ch_test",
                "payment_intent": "pi_test_paid",
                "amount_refunded": 1000,
            },
        )
        == "partial"
    )
    assert (
        db.process_refund_event(
            "evt_refund_full",
            {
                "id": "ch_test",
                "payment_intent": "pi_test_paid",
                "amount_refunded": 2500,
            },
        )
        == "full"
    )

    order = db.confirmation_lookup("cs_test_paid")
    assert order["payment_state"] == "paid"
    assert order["fulfillment_state"] == "unfulfilled"
    assert order["review_state"] == "clear"
    assert order["refund_state"] == "full"


def test_checkout_http_retry_reuses_reservation(catalog_factory, monkeypatch):
    variant_id = _database(catalog_factory)
    calls = 0

    def create_session(checkout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise stripe.APIConnectionError("provider timeout")
        return SimpleNamespace(
            id="cs_http_retry",
            url="https://checkout.stripe.test/session",
            expires_at=int((datetime.now(UTC) + timedelta(minutes=31)).timestamp()),
        )

    monkeypatch.setattr(store_router, "create_checkout_session", create_session)
    app.state.store_enabled = True
    client = TestClient(app)
    payload = {"items": [{"variant_id": variant_id, "qty": 1}]}

    uncertain = client.post("/store/checkout", json=payload)
    assert uncertain.status_code == 502
    checkout_id = uncertain.json()["checkout_id"]

    retried = client.post(
        "/store/checkout",
        json={**payload, "checkout_id": checkout_id},
    )
    assert retried.status_code == 200
    assert retried.json()["url"] == "https://checkout.stripe.test/session"
    with db.connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM checkouts").fetchone()["count"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM inventory_reservations "
                "WHERE state='active'"
            ).fetchone()["count"]
            == 1
        )


def test_checkout_http_rejects_and_releases_a_stale_retry(catalog_factory, monkeypatch):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    stale_expiry = db._timestamp(datetime.now(UTC) + timedelta(minutes=29))
    with db.connection(write=True) as conn:
        conn.execute(
            "UPDATE checkouts SET expires_at=%s WHERE id=%s",
            (stale_expiry, checkout["id"]),
        )
        conn.execute(
            "UPDATE inventory_reservations SET expires_at=%s WHERE checkout_id=%s",
            (stale_expiry, checkout["id"]),
        )

    app.state.store_enabled = True
    response = TestClient(app).post(
        "/store/checkout",
        json={
            "items": [{"variant_id": variant_id, "qty": 1}],
            "checkout_id": checkout["id"],
        },
    )

    assert response.status_code == 409
    with db.connection() as conn:
        assert (
            conn.execute("SELECT status FROM checkouts").fetchone()["status"]
            == "failed"
        )
        assert (
            conn.execute("SELECT state FROM inventory_reservations").fetchone()["state"]
            == "released"
        )


def test_stripe_client_uses_scoped_client_and_ignores_api_key_for_webhooks(monkeypatch):
    created = {}

    class Sessions:
        def create(self, params, options):
            created.update(params=params, options=options)
            return SimpleNamespace(id="cs_test")

    class Client:
        def __init__(self, api_key):
            created["api_key"] = api_key
            self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()))

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_scoped")
    monkeypatch.setenv("STORE_PUBLIC_ORIGIN", "https://example.test")
    monkeypatch.setattr(stripe, "StripeClient", Client)
    checkout = {
        "id": "checkout-id",
        "currency": "usd",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=31)).isoformat(),
        "items": [
            {
                "sku": "opaque.inventory/001",
                "variant_id": 42,
                "product_name": "RFID Tool",
                "variant_name": "",
                "unit_amount_cents": 2500,
                "quantity": 1,
            }
        ],
    }

    stripe_client.create_checkout_session(checkout)

    assert created["api_key"] == "sk_test_scoped"
    assert created["options"] == {"idempotency_key": "checkout:checkout-id"}
    metadata = created["params"]["line_items"][0]["price_data"]["product_data"]["metadata"]
    assert metadata == {"variant_id": "42", "sku": "opaque.inventory/001"}

    monkeypatch.delenv("STRIPE_SECRET_KEY")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: (payload, signature, secret),
    )
    assert stripe_client.construct_webhook_event(b"{}", "sig") == (
        b"{}",
        "sig",
        "whsec_test",
    )


def test_webhook_http_rejects_invalid_and_replays_paid_event_once(
    catalog_factory, monkeypatch
):
    variant_id = _database(catalog_factory)
    app.state.store_enabled = True
    client = TestClient(app)

    invalid = client.post(
        "/store/webhook", content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert invalid.status_code == 400

    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    event = {
        "id": "evt_http_paid",
        "type": "checkout.session.completed",
        "created": 123,
        "data": {"object": _paid_session(checkout)},
    }
    monkeypatch.setattr(
        store_router,
        "construct_webhook_event",
        lambda _payload, _signature: event,
    )

    first = client.post("/store/webhook", content=b"{}")
    replay = client.post("/store/webhook", content=b"{}")
    assert first.status_code == replay.status_code == 200
    with db.connection() as conn:
        assert (
            conn.execute("SELECT stock_on_hand FROM variants").fetchone()[
                "stock_on_hand"
            ]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
            == 1
        )
        ledger = conn.execute(
            "SELECT state,attempts FROM stripe_events WHERE event_id='evt_http_paid'"
        ).fetchone()
    assert dict(ledger) == {"state": "processed", "attempts": 1}


def test_null_sku_purchase_survives_paid_webhook(catalog_factory, monkeypatch):
    product = catalog_factory.product(variants=[{"sku": None, "stock": 1}])
    variant_id = product["variants"][0]["id"]
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    assert checkout["items"][0]["sku"] is None
    assert checkout["items"][0]["variant_id"] == variant_id
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    monkeypatch.setattr(store_router, "construct_webhook_event", lambda *_: {
        "id": "evt_null_sku", "type": "checkout.session.completed", "created": 123,
        "data": {"object": _paid_session(checkout)},
    })
    with TestClient(app) as client:
        assert client.post("/store/webhook", content=b"{}").status_code == 200
    with db.connection() as conn:
        assert conn.execute(
            "SELECT variant_id,sku,quantity,unit_amount_cents FROM order_items"
        ).fetchone() == {
            "variant_id": variant_id, "sku": None, "quantity": 1, "unit_amount_cents": 2500,
        }
        assert conn.execute("SELECT stock_on_hand FROM variants").fetchone()["stock_on_hand"] == 0
        assert conn.execute("SELECT state FROM inventory_reservations").fetchone()["state"] == "consumed"


def test_stripe_omits_null_sku_metadata(monkeypatch):
    created = {}

    class Sessions:
        def create(self, params, options):
            created.update(params)
            return SimpleNamespace(id="cs_null_sku")

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STORE_PUBLIC_ORIGIN", "https://example.test")
    monkeypatch.setattr(stripe, "StripeClient", lambda _: SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions())),
    ))
    stripe_client.create_checkout_session({
        "id": "checkout-null", "currency": "usd",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=35)).isoformat(),
        "items": [{"variant_id": 7, "sku": None, "product_name": "Tool",
                   "variant_name": "Blue", "unit_amount_cents": 500, "quantity": 1}],
    })
    product_data = created["line_items"][0]["price_data"]["product_data"]
    assert product_data["metadata"] == {"variant_id": "7"}
    assert product_data["name"] == "Tool — Blue"


def test_reservation_uses_distinct_ids_for_null_skus(catalog_factory):
    product = catalog_factory.product(variants=[
        {"name": "Blue", "price_cents": 500, "stock": 2},
        {"name": "Black", "price_cents": 1250, "stock": 3},
    ])
    first, second = [v["id"] for v in product["variants"]]
    checkout = db.reserve_checkout([
        {"variant_id": second, "qty": 2}, {"variant_id": first, "qty": 1},
        {"variant_id": first, "qty": 1},
    ])
    assert checkout["subtotal_cents"] == 3500
    assert [(i["variant_id"], i["quantity"]) for i in checkout["items"]] == [(first, 2), (second, 2)]
    assert all(i["sku"] is None for i in checkout["items"])
    normalized, problems = db.normalize_cart([{"variant_id": first, "qty": 1}])
    assert normalized[0]["available_stock"] == 0
    assert problems == [{"variant_id": first, "reason": "stock", "available_stock": 0}]


@pytest.mark.parametrize("make_item", [
    lambda v: {"variant_id": 0, "qty": 1}, lambda v: {"variant_id": -1, "qty": 1},
    lambda v: {"variant_id": True, "qty": 1}, lambda v: {"variant_id": str(v), "qty": 1},
    lambda v: {"variant_id": v, "qty": 0}, lambda v: {"variant_id": v, "qty": 100},
    lambda v: {"variant_id": v, "qty": True}, lambda v: {"variant_id": v, "qty": 1.5},
])
def test_invalid_cart_items_are_rejected(catalog_factory, make_item):
    # Stock covers every quantity so only the item's shape can cause the rejection.
    variant_id = _database(catalog_factory, stock=200)
    with pytest.raises(db.CartUnavailable):
        db.reserve_checkout([make_item(variant_id)])


def test_cart_http_validates_variant_ids_and_quantities(catalog_factory):
    with TestClient(app) as client:
        for item in ({"sku": "obsolete", "qty": 1}, {"variant_id": 0, "qty": 1},
                     {"variant_id": 1, "qty": 100}):
            assert client.post("/store/api/cart-info", json={"items": [item]}).status_code == 422
            assert client.post("/store/checkout", json={"items": [item]}).status_code == 422


def test_unavailable_item_rolls_back_entire_reservation(catalog_factory):
    variant_id = _database(catalog_factory)
    with pytest.raises(db.CartUnavailable):
        db.reserve_checkout([{"variant_id": variant_id, "qty": 1}, {"variant_id": 9999, "qty": 1}])
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS count FROM checkouts").fetchone()["count"] == 0
        assert conn.execute("SELECT count(*) AS count FROM inventory_reservations").fetchone()["count"] == 0


def test_paid_event_uses_checkout_snapshot_after_catalog_edits(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    with db.connection() as conn:
        conn.execute(
            "UPDATE variants SET sku=NULL,price_cents=9999,published=false WHERE id=%s",
            (variant_id,),
        )
        conn.execute("UPDATE products SET name='New name',published=false")
    db.process_paid_event("evt_snapshot", _paid_session(checkout))
    with db.connection() as conn:
        assert conn.execute(
            "SELECT variant_id,sku,product_name,unit_amount_cents FROM order_items"
        ).fetchone() == {
            "variant_id": variant_id, "sku": "opaque.inventory/001",
            "product_name": "RFID Test Tool", "unit_amount_cents": 2500,
        }


def test_order_items_must_name_an_existing_variant(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.process_paid_event("evt_fk", _paid_session(checkout))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.connection() as conn:
        conn.execute("UPDATE order_items SET variant_id=%s", (variant_id + 1000,))
    with db.connection() as conn:
        # Items from before the database catalog have no variant.
        conn.execute("UPDATE order_items SET variant_id=NULL")


def test_expired_webhook_releases_once_and_does_not_restock(catalog_factory):
    variant_id = _database(catalog_factory)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    session = {"id": "cs_expired", "metadata": {"checkout_id": checkout["id"]}}
    db.attach_stripe_session(checkout["id"], session["id"])
    assert db.process_expired_event("evt_expired", session) == "expired"
    assert db.process_expired_event("evt_expired", session) == "duplicate"
    assert db.get_product_by_slug("rfid-test-tool")["variants"][0]["available_stock"] == 1
    with pytest.raises(db.CheckoutConflict):
        db.process_paid_event("evt_too_late", _paid_session(checkout))
def _signed_webhook(event, secret="whsec_test"):
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return payload, {"stripe-signature": f"t={timestamp},v1={digest}"}


def test_webhook_http_handles_real_signed_stripe_events(catalog_factory, monkeypatch):
    # Real stripe.Event objects (not dicts) must reach the db layer as mappings.
    variant_id = _database(catalog_factory)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    client = TestClient(app)
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    db.attach_stripe_session(checkout["id"], "cs_test_paid")
    events = {
        "evt_signed_paid": {
            "type": "checkout.session.completed",
            "object": {"object": "checkout.session", **_paid_session(checkout)},
        },
        "evt_signed_charge": {
            "type": "charge.succeeded",
            "object": {"id": "ch_test", "object": "charge"},
        },
    }

    for event_id, event in events.items():
        payload, headers = _signed_webhook(
            {
                "id": event_id,
                "object": "event",
                "type": event["type"],
                "created": 123,
                "data": {"object": event["object"]},
            }
        )
        response = client.post("/store/webhook", content=payload, headers=headers)
        assert response.status_code == 200, response.text

    with db.connection() as conn:
        states = {
            row["event_id"]: row["state"]
            for row in conn.execute("SELECT event_id,state FROM stripe_events")
        }
        orders = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()
    assert states == {"evt_signed_paid": "processed", "evt_signed_charge": "ignored"}
    assert orders["count"] == 1


def test_webhook_http_logs_unexpected_failures_as_json(
    catalog_factory, monkeypatch, caplog
):
    _database(catalog_factory)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "process_ignored_event", explode)
    payload, headers = _signed_webhook(
        {
            "id": "evt_signed_boom",
            "object": "event",
            "type": "charge.updated",
            "created": 123,
            "data": {"object": {"id": "ch_test", "object": "charge"}},
        }
    )

    response = TestClient(app).post(
        "/store/webhook", content=payload, headers=headers
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Webhook processing failed and will be retried."
    }
    assert "store_webhook_failed event_id=evt_signed_boom" in caplog.text
