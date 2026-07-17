import asyncio
import sqlite3

from src.store import db
from src.store import router as store_router


def _insert_order(payment_intent: str = "pi_test") -> None:
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO orders(
                stripe_session_id, payment_intent, amount_total_cents,
                currency, status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            ("cs_test", payment_intent, 5000, "usd", "paid", db.utc_now()),
        )


def test_refund_updates_amount_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "store.db")
    db.init_db()
    _insert_order()

    assert db.record_refund_from_charge(
        {"payment_intent": "pi_test", "amount": 5000, "amount_refunded": 1200}
    ) == "partially_refunded"
    assert db.record_refund_from_charge(
        {"payment_intent": "pi_test", "amount": 5000, "amount_refunded": 5000}
    ) == "refunded"
    assert db.record_refund_from_charge(
        {"payment_intent": "pi_test", "amount": 5000, "amount_refunded": 1200}
    ) == "refunded"

    with db.connection() as conn:
        order = conn.execute(
            "SELECT status, amount_refunded_cents FROM orders"
        ).fetchone()
    assert dict(order) == {"status": "refunded", "amount_refunded_cents": 5000}


def test_refund_for_unknown_order_requests_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "store.db")
    db.init_db()
    monkeypatch.setattr(
        store_router,
        "construct_webhook_event",
        lambda _payload, _signature: {
            "type": "charge.refunded",
            "data": {
                "object": {
                    "payment_intent": "pi_missing",
                    "amount": 5000,
                    "amount_refunded": 5000,
                }
            },
        },
    )

    class Request:
        headers = {"stripe-signature": "test"}

        async def body(self):
            return b"{}"

    response = asyncio.run(store_router.store_webhook(Request()))
    assert response.status_code == 409


def test_init_db_migrates_existing_orders_table(tmp_path, monkeypatch):
    database = tmp_path / "store.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE orders(
                id INTEGER PRIMARY KEY,
                stripe_session_id TEXT UNIQUE NOT NULL,
                payment_intent TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    monkeypatch.setattr(db, "DB_PATH", database)

    db.init_db()

    with db.connection() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
    assert "amount_refunded_cents" in columns
