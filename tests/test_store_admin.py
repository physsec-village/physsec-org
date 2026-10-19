import re

import pytest

from fastapi.testclient import TestClient

from src.main import app
from src.store import admin_auth, db


@pytest.fixture
def anonymous():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(anonymous):
    page = anonymous.get("/store/admin/login")
    response = anonymous.post(
        "/store/admin/login",
        data={"csrf_token": _csrf(page.text), "username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return anonymous


def _version(page: str) -> str:
    match = re.search(r'name="version" value="([^"]+)"', page)
    assert match, "form has no version"
    return match.group(1)


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page)
    assert match, "form has no CSRF token"
    return match.group(1)


def _product(base_sku: str = "PSV-RFID-001") -> dict:
    product = db.get_product_by_id(base_sku)
    assert product is not None
    return product


def _variant_form(product: dict, csrf: str, **overrides) -> dict:
    variant = product["variants"][0]
    form = {
        "csrf_token": csrf,
        "name": product["name"],
        "description": product["description"],
        "published": "true",
        "version": product["updated_at"].isoformat(),
        "variant_id": str(variant["id"]),
        "variant_name": variant["name"],
        "variant_upc": variant["upc"],
        "variant_price": "10.00",
        "variant_stock": str(variant["stock_on_hand"]),
        "variant_expected_stock": str(variant["stock_on_hand"]),
    }
    form.update(overrides)
    return form


def _paid_order() -> str:
    product = _product()
    sku = product["variants"][0]["sku"]
    with db.connection() as conn:
        conn.execute("UPDATE variants SET stock_on_hand=1 WHERE sku=%s", (sku,))
    checkout = db.reserve_checkout([{"sku": sku, "qty": 1}])
    return db.process_paid_event(
        "evt_admin_paid",
        {
            "id": "cs_admin_paid",
            "metadata": {"checkout_id": checkout["id"]},
            "payment_status": "paid",
            "payment_intent": "pi_admin_paid",
            "currency": "usd",
            "amount_subtotal": checkout["subtotal_cents"],
            "amount_total": checkout["subtotal_cents"],
            "customer_details": {"email": "buyer@example.com"},
            "collected_information": {
                "shipping_details": {
                    "name": "Pat Buyer",
                    "address": {
                        "line1": "1 Main St",
                        "city": "Las Vegas",
                        "state": "NV",
                        "postal_code": "89101",
                        "country": "US",
                    },
                }
            },
        },
    )


def test_admin_requires_sign_in(anonymous):
    response = anonymous.get("/store/admin", follow_redirects=False)
    anonymous.cookies.set(admin_auth.SESSION_COOKIE, "0" * 64)
    forged = anonymous.get("/store/admin", follow_redirects=False)
    anonymous.cookies.clear()
    post = anonymous.post("/store/admin/orders/x", follow_redirects=False)

    for blocked in (response, forged, post):
        assert blocked.status_code == 303
        assert blocked.headers["location"].endswith("/store/admin/login")
        assert blocked.headers["cache-control"] == "no-store"


def test_sign_in_rejects_wrong_credentials_and_bad_tokens(anonymous):
    csrf = _csrf(anonymous.get("/store/admin/login").text)
    wrong = anonymous.post(
        "/store/admin/login",
        data={"csrf_token": csrf, "username": "admin", "password": "nope"},
    )
    no_token = anonymous.post(
        "/store/admin/login", data={"username": "admin", "password": "admin"}
    )

    assert wrong.status_code == 401
    assert "Wrong username or password." in wrong.text
    assert no_token.status_code == 403
    assert admin_auth.SESSION_COOKIE not in anonymous.cookies


def test_sign_in_and_sign_out(client):
    page = client.get("/store/admin")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "noindex" in page.headers["x-robots-tag"]
    assert "PSV-RFID-001" in page.text

    out = client.post(
        "/store/admin/logout",
        data={"csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )

    assert out.status_code == 303
    assert client.get("/store/admin", follow_redirects=False).status_code == 303


def test_admin_is_hidden_while_store_is_disabled(anonymous):
    app.state.store_enabled = False
    try:
        response = anonymous.get("/store/admin/login")
    finally:
        app.state.store_enabled = True

    assert response.status_code == 404


def test_forms_require_the_csrf_token(client):
    product = _product()
    url = f"/store/admin/products/{product['id']}"

    missing = client.post(url, data=_variant_form(product, ""))
    forged = client.post(url, data=_variant_form(product, "0" * 64))

    assert missing.status_code == 403
    assert forged.status_code == 403
    assert (
        _product()["variants"][0]["price_cents"]
        == product["variants"][0]["price_cents"]
    )


def test_update_product_details_price_and_stock(client):
    product = _product()
    page = client.get(f"/store/admin/products/{product['id']}")
    csrf = _csrf(page.text)

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(
            product,
            csrf,
            name="Proxmark Renamed",
            variant_price="12.34",
            variant_stock="7",
            featured="true",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("?notice=saved")
    updated = _product()
    assert updated["name"] == "Proxmark Renamed"
    assert updated["featured"] is True
    assert updated["published"] is True
    assert updated["variants"][0]["price_cents"] == 1234
    assert updated["variants"][0]["stock_on_hand"] == 7
    saved = client.get(response.headers["location"])
    assert "Changes saved." in saved.text

    # Unchecked boxes are absent from the form and unpublish the product.
    form = _variant_form(updated, csrf, variant_price="12.34")
    del form["published"]
    client.post(f"/store/admin/products/{product['id']}", data=form)
    assert _product()["published"] is False


def test_stock_edit_rejects_a_stale_value(client):
    product = _product()
    csrf = _csrf(client.get("/store/admin/products/new").text)
    variant = product["variants"][0]
    with db.connection() as conn:
        conn.execute(
            "UPDATE variants SET stock_on_hand=5 WHERE id=%s", (variant["id"],)
        )

    stale = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(
            product, csrf, variant_stock="20", variant_expected_stock="0"
        ),
    )
    # Leaving stock untouched still saves other fields without clobbering it.
    untouched = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(
            product,
            csrf,
            variant_price="15.00",
            variant_stock="0",
            variant_expected_stock="0",
        ),
        follow_redirects=False,
    )

    assert stale.status_code == 400
    assert "changed to 5 while you were editing" in stale.text
    assert untouched.status_code == 303
    variant = _product()["variants"][0]
    assert variant["stock_on_hand"] == 5
    assert variant["price_cents"] == 1500


def test_stock_cannot_drop_below_reservations(client):
    product = _product()
    variant = product["variants"][0]
    with db.connection() as conn:
        conn.execute(
            "UPDATE variants SET stock_on_hand=3 WHERE id=%s", (variant["id"],)
        )
    db.reserve_checkout([{"sku": variant["sku"], "qty": 2}])
    page = client.get(f"/store/admin/products/{product['id']}")
    assert re.search(r">\s*2\s*</td>", page.text)

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(
            product,
            _csrf(page.text),
            variant_stock="1",
            variant_expected_stock="3",
        ),
    )

    assert response.status_code == 400
    assert "below the 2 units reserved" in response.text
    assert _product()["variants"][0]["stock_on_hand"] == 3


def test_invalid_price_is_reported(client):
    product = _product()
    page = client.get(f"/store/admin/products/{product['id']}")
    csrf = _csrf(page.text)

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(product, csrf, variant_price="-1"),
    )

    assert response.status_code == 400
    assert "dollar amount" in response.text


def test_create_product_and_add_variant(client):
    csrf = _csrf(client.get("/store/admin/products/new").text)
    created = client.post(
        "/store/admin/products",
        data={
            "csrf_token": csrf,
            "name": "Test Shim",
            "base_sku": "psv-byp-901",
            "price": "9.50",
            "stock": "4",
            "published": "true",
        },
        follow_redirects=False,
    )
    duplicate = client.post(
        "/store/admin/products",
        data={
            "csrf_token": csrf,
            "name": "Again",
            "base_sku": "PSV-BYP-901",
            "price": "1",
        },
    )
    bad_sku = client.post(
        "/store/admin/products",
        data={"csrf_token": csrf, "name": "Bad", "base_sku": "SHIM", "price": "1"},
    )

    assert created.status_code == 303
    product = _product("PSV-BYP-901")
    assert product["slug"] == "psv-byp-901"
    assert product["category_label"] == "Bypass Tools"
    assert product["variants"][0]["price_cents"] == 950
    assert product["variants"][0]["stock_on_hand"] == 4
    assert duplicate.status_code == 400
    assert "already in use" in duplicate.text
    assert bad_sku.status_code == 400
    assert "PSV-CATEGORY-NNN" in bad_sku.text
    assert client.get("/store/product/PSV-BYP-901").status_code == 200

    variant_url = f"/store/admin/products/{product['id']}/variants"
    added = client.post(
        variant_url,
        data={
            "csrf_token": csrf,
            "sku": "PSV-BYP-901-002",
            "name": "Wide",
            "price": "11",
            "stock": "2",
        },
        follow_redirects=False,
    )
    foreign = client.post(
        variant_url,
        data={"csrf_token": csrf, "sku": "PSV-BYP-902-001", "price": "1"},
    )

    assert added.status_code == 303
    variants = _product("PSV-BYP-901")["variants"]
    assert [v["sku"] for v in variants] == ["PSV-BYP-901", "PSV-BYP-901-002"]
    assert variants[1]["position"] == 1
    assert foreign.status_code == 400
    assert "must start with PSV-BYP-901" in foreign.text


def test_orders_list_detail_and_status_update(client):
    order_id = _paid_order()

    listing = client.get("/store/admin/orders")
    filtered = client.get("/store/admin/orders?fulfillment=shipped")
    detail = client.get(f"/store/admin/orders/{order_id}")

    assert listing.status_code == 200
    assert order_id[:8] in listing.text
    assert "buyer@example.com" in listing.text
    assert order_id[:8] not in filtered.text
    assert detail.status_code == 200
    assert "Pat Buyer" in detail.text
    assert "Las Vegas" in detail.text

    csrf = _csrf(detail.text)
    version = _version(detail.text)
    updated = client.post(
        f"/store/admin/orders/{order_id}",
        data={
            "csrf_token": csrf,
            "version": version,
            "fulfillment_state": "shipped",
            "review_state": "needs_review",
            "review_reason": "Address check",
        },
        follow_redirects=False,
    )
    invalid = client.post(
        f"/store/admin/orders/{order_id}",
        data={
            "csrf_token": csrf,
            "fulfillment_state": "teleported",
            "review_state": "clear",
        },
    )

    assert updated.status_code == 303
    order = db.admin_order(order_id)
    assert order["fulfillment_state"] == "shipped"
    assert order["review_state"] == "needs_review"
    assert order["review_reason"] == "Address check"
    assert order["payment_state"] == "paid"
    assert invalid.status_code == 400
    assert db.admin_order(order_id)["fulfillment_state"] == "shipped"
    assert client.get("/store/admin/orders/missing").status_code == 404


def test_stale_product_form_does_not_undo_a_newer_edit(client):
    product = _product()
    page = client.get(f"/store/admin/products/{product['id']}")
    csrf = _csrf(page.text)
    first = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(product, csrf, variant_price="50.00"),
        follow_redirects=False,
    )
    stale = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(product, csrf, description="Edited in an old tab"),
    )

    assert first.status_code == 303
    assert stale.status_code == 400
    assert "changed after you loaded the page" in stale.text
    current = _product()
    assert current["variants"][0]["price_cents"] == 5000
    assert current["description"] == product["description"]


def test_stale_order_form_does_not_undo_a_newer_edit(client):
    order_id = _paid_order()
    detail = client.get(f"/store/admin/orders/{order_id}").text
    form = {"csrf_token": _csrf(detail), "version": _version(detail)}

    shipped = client.post(
        f"/store/admin/orders/{order_id}",
        data={**form, "fulfillment_state": "shipped", "review_state": "clear"},
        follow_redirects=False,
    )
    stale = client.post(
        f"/store/admin/orders/{order_id}",
        data={
            **form,
            "fulfillment_state": "unfulfilled",
            "review_state": "clear",
            "review_reason": "note from an old tab",
        },
    )

    assert shipped.status_code == 303
    assert stale.status_code == 400
    assert "changed after you loaded the page" in stale.text
    order = db.admin_order(order_id)
    assert order["fulfillment_state"] == "shipped"
    assert order["review_reason"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("variant_price", "21474836.48"), ("variant_stock", "2147483648")],
)
def test_values_beyond_database_limits_are_rejected(client, field, value):
    product = _product()
    csrf = _csrf(client.get(f"/store/admin/products/{product['id']}").text)

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(product, csrf, **{field: value}),
    )
    created = client.post(
        "/store/admin/products",
        data={
            "csrf_token": csrf,
            "name": "Huge",
            "base_sku": "PSV-BYP-950",
            "price": "21474836.48",
        },
    )

    assert response.status_code == 400
    assert "less than or equal to 2147483647" in response.text
    assert created.status_code == 400
    assert db.get_product_by_id("PSV-BYP-950") is None
