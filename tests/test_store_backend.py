from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import stripe
from fastapi.testclient import TestClient

from src.main import app
from src.store import db, seed, stripe_client
from src.store import router as store_router
from src.store.config import bootstrap_stock, reservation_minutes
from src.store.models import ProductInput, VariantInput
from src.store.storefront import ProductView, VariantView


def _database(tmp_path, *, stock: int = 1):
    path = tmp_path / "store.db"
    db.init_db(path)
    db.create_product(
        ProductInput(
            name="RFID Test Tool",
            base_sku="PSV-RFID-001",
            description="Test product",
            category_label="RFID",
            variants=[
                VariantInput(
                    sku="PSV-RFID-001",
                    upc="123456789012",
                    price_cents=2500,
                    stock_on_hand=stock,
                )
            ],
        ),
        db_path=path,
    )
    return path


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


def test_schema_and_rfid_catalog(tmp_path):
    path = _database(tmp_path)

    assert db.readiness(path) == {"ready": True, "schema_version": 1}
    product = db.get_published_products(db_path=path)[0]
    assert product["base_sku"] == "PSV-RFID-001"
    assert product["price_cents"] == 2500
    assert product["variants"][0]["available_stock"] == 1


@pytest.mark.parametrize(
    ("name", "value", "reader"),
    [
        ("STORE_RESERVATION_MINUTES", "not-a-number", reservation_minutes),
        ("STORE_RESERVATION_MINUTES", "30", reservation_minutes),
        ("STORE_RESERVATION_MINUTES", "1441", reservation_minutes),
        ("STORE_BOOTSTRAP_STOCK", "not-a-number", bootstrap_stock),
        ("STORE_BOOTSTRAP_STOCK", "-1", bootstrap_stock),
    ],
)
def test_store_numeric_configuration_is_validated(monkeypatch, name, value, reader):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        reader()


def test_product_default_variant_prefers_available_stock():
    variants = (
        VariantView("001", "Sold out", "PSV-RFID-001-001", "", 1000, 0),
        VariantView("002", "Available", "PSV-RFID-001-002", "", 1000, 2),
    )
    product = ProductView(
        id="PSV-RFID-001",
        name="RFID Tool",
        cat="RFID",
        cat_label="RFID",
        sku=variants[0].sku,
        upc="",
        desc="",
        featured=False,
        price_cents=1000,
        price_str="$10.00",
        price_varies=False,
        variants=variants,
        available_stock=2,
    )

    assert product.default_variant.sku == "PSV-RFID-001-002"


def test_cart_normalization_caps_duplicate_sku_totals(tmp_path):
    path = _database(tmp_path, stock=200)
    normalized, problems = db.normalize_cart(
        [
            {"sku": "PSV-RFID-001", "qty": 60},
            {"sku": "psv-rfid-001", "qty": 60},
        ],
        db_path=path,
    )

    assert normalized[0]["qty"] == 60
    assert problems == [{"sku": "PSV-RFID-001", "reason": "quantity"}]


def test_catalog_bootstrap_resumes_a_partial_import(tmp_path):
    path = _database(tmp_path)

    imported = seed.bootstrap_catalog(path)

    assert imported > 0
    assert seed.bootstrap_catalog(path) == 0
    assert db.get_product_by_id("PSV-BYP-001", db_path=path) is not None


def test_reservation_prevents_overselling_and_expiry_releases(tmp_path):
    path = _database(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(
                db.reserve_checkout,
                [{"sku": "PSV-RFID-001", "qty": 1}],
                db_path=path,
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
        db.cleanup_expired_reservations(
            now=datetime.now(UTC) + timedelta(hours=1), db_path=path
        )
        == 1
    )
    replacement = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    assert replacement["status"] == "creating"


def test_paid_event_is_atomic_and_idempotent(tmp_path):
    path = _database(tmp_path)
    checkout = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    db.attach_stripe_session(checkout["id"], "cs_test_paid", db_path=path)
    session = _paid_session(checkout)

    order_id = db.process_paid_event("evt_paid", session, db_path=path)
    assert db.process_paid_event("evt_paid", session, db_path=path) == "duplicate"
    assert (
        db.process_paid_event(
            "evt_async_paid",
            session,
            event_type="checkout.session.async_payment_succeeded",
            db_path=path,
        )
        == "duplicate"
    )

    confirmation = db.confirmation_lookup("cs_test_paid", db_path=path)
    assert confirmation["id"] == order_id
    assert confirmation["payment_state"] == "paid"
    assert confirmation["fulfillment_state"] == "unfulfilled"
    with db.connection(path) as conn:
        assert conn.execute("SELECT stock_on_hand FROM variants").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0] == 2


def test_failed_paid_event_rolls_back_then_can_be_recorded(tmp_path):
    path = _database(tmp_path)
    missing = {
        "id": "cs_missing",
        "client_reference_id": "missing-checkout",
        "metadata": {"checkout_id": "missing-checkout"},
        "payment_status": "paid",
        "currency": "usd",
        "amount_subtotal": 2500,
    }

    with pytest.raises(db.CheckoutConflict):
        db.process_paid_event("evt_missing", missing, db_path=path)
    db.record_event_failure(
        "evt_missing",
        "checkout.session.completed",
        "checkout_conflict",
        "Paid checkout is missing.",
        db_path=path,
    )

    with db.connection(path) as conn:
        event = conn.execute(
            "SELECT state,attempts,last_error_code FROM stripe_events"
        ).fetchone()
    assert dict(event) == {
        "state": "failed",
        "attempts": 1,
        "last_error_code": "checkout_conflict",
    }


def test_paid_event_requires_explicit_payment_status(tmp_path):
    path = _database(tmp_path)
    checkout = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    db.attach_stripe_session(checkout["id"], "cs_test_paid", db_path=path)
    session = _paid_session(checkout)
    session.pop("payment_status")

    with pytest.raises(db.CheckoutConflict, match="not paid"):
        db.process_paid_event("evt_missing_status", session, db_path=path)


def test_refund_state_does_not_overwrite_other_order_states(tmp_path):
    path = _database(tmp_path)
    checkout = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    db.attach_stripe_session(checkout["id"], "cs_test_paid", db_path=path)
    db.process_paid_event("evt_paid", _paid_session(checkout), db_path=path)

    assert (
        db.process_refund_event(
            "evt_refund_partial",
            {
                "id": "ch_test",
                "payment_intent": "pi_test_paid",
                "amount_refunded": 1000,
            },
            db_path=path,
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
            db_path=path,
        )
        == "full"
    )

    order = db.confirmation_lookup("cs_test_paid", db_path=path)
    assert order["payment_state"] == "paid"
    assert order["fulfillment_state"] == "unfulfilled"
    assert order["review_state"] == "clear"
    assert order["refund_state"] == "full"


def test_checkout_http_retry_reuses_reservation(tmp_path, monkeypatch):
    path = _database(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", path)
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
    client = TestClient(app)
    payload = {"items": [{"sku": "PSV-RFID-001", "qty": 1}]}

    uncertain = client.post("/store/checkout", json=payload)
    assert uncertain.status_code == 502
    checkout_id = uncertain.json()["checkout_id"]

    retried = client.post(
        "/store/checkout",
        json={**payload, "checkout_id": checkout_id},
    )
    assert retried.status_code == 200
    assert retried.json()["url"] == "https://checkout.stripe.test/session"
    with db.connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM checkouts").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM inventory_reservations WHERE state='active'"
            ).fetchone()[0]
            == 1
        )


def test_checkout_http_rejects_and_releases_a_stale_retry(tmp_path, monkeypatch):
    path = _database(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", path)
    checkout = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    stale_expiry = db._timestamp(datetime.now(UTC) + timedelta(minutes=29))
    with db.connection(path, write=True) as conn:
        conn.execute(
            "UPDATE checkouts SET expires_at=? WHERE id=?",
            (stale_expiry, checkout["id"]),
        )
        conn.execute(
            "UPDATE inventory_reservations SET expires_at=? WHERE checkout_id=?",
            (stale_expiry, checkout["id"]),
        )

    response = TestClient(app).post(
        "/store/checkout",
        json={
            "items": [{"sku": "PSV-RFID-001", "qty": 1}],
            "checkout_id": checkout["id"],
        },
    )

    assert response.status_code == 409
    with db.connection(path) as conn:
        assert conn.execute("SELECT status FROM checkouts").fetchone()[0] == "failed"
        assert (
            conn.execute("SELECT state FROM inventory_reservations").fetchone()[0]
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
                "sku": "PSV-RFID-001",
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
    tmp_path, monkeypatch
):
    path = _database(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", path)
    client = TestClient(app)

    invalid = client.post(
        "/store/webhook", content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert invalid.status_code == 400

    checkout = db.reserve_checkout([{"sku": "PSV-RFID-001", "qty": 1}], db_path=path)
    db.attach_stripe_session(checkout["id"], "cs_test_paid", db_path=path)
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
    with db.connection(path) as conn:
        assert conn.execute("SELECT stock_on_hand FROM variants").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        ledger = conn.execute(
            "SELECT state,attempts FROM stripe_events WHERE event_id='evt_http_paid'"
        ).fetchone()
    assert dict(ledger) == {"state": "processed", "attempts": 1}
