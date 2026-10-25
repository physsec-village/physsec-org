import re

import pytest

from fastapi.testclient import TestClient

from src.main import app
from src.store import admin_auth, db


@pytest.fixture
def anonymous():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def catalog(catalog_factory):
    collection = catalog_factory.collection("rfid", "RFID")
    group = catalog_factory.group(collection)
    product = catalog_factory.product(
        slug="proxmark", name="Proxmark",
        variants=[{"sku": "PSV-RFID-001", "price_cents": 2500, "stock": 0}],
    )
    catalog_factory.add(group, product)
    return {"product": product, "collection": collection, "group": group}


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


def _product(slug: str = "proxmark") -> dict:
    with db.connection() as conn:
        row = conn.execute("SELECT id FROM products WHERE slug=%s", (slug,)).fetchone()
    assert row is not None
    return db.admin_product(row["id"])


def _variant_form(product: dict, csrf: str, **overrides) -> dict:
    variant = product["variants"][0]
    form = {
        "csrf_token": csrf,
        "name": product["name"],
        "slug": product["slug"],
        "description": product["description"],
        "features": "\n".join(product["features"]),
        "group_id": [str(group_id) for group_id in product["group_ids"]],
        "published": "true",
        "version": product["updated_at"].isoformat(),
        "variant_id": str(variant["id"]),
        "variant_name": variant["name"],
        "variant_sku": variant["sku"] or "",
        "variant_upc": variant["upc"] or "",
        "variant_price": "10.00",
        "variant_stock": str(variant["stock_on_hand"]),
        "variant_expected_stock": str(variant["stock_on_hand"]),
        "variant_published": [str(variant["id"])] if variant["published"] else [],
    }
    form.update(overrides)
    return form


def _paid_order() -> str:
    variant_id = _product()["variants"][0]["id"]
    with db.connection() as conn:
        conn.execute("UPDATE variants SET stock_on_hand=1 WHERE id=%s", (variant_id,))
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
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
    assert "Proxmark" in page.text
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
    assert "Stock for Proxmark changed to 5 while you were editing" in stale.text
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
    db.reserve_checkout([{"variant_id": variant["id"], "qty": 2}])
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


def test_create_product_and_add_variant(client, catalog):
    csrf = _csrf(client.get("/store/admin/products/new").text)
    group_id = str(catalog["group"]["id"])
    created = client.post(
        "/store/admin/products",
        data={
            "csrf_token": csrf,
            "name": "Test Shim",
            "features": "Spring steel\n\n  Pack of 5  ",
            "group_id": [group_id],
            "price": "9.50",
            "stock": "4",
            "published": "true",
        },
        follow_redirects=False,
    )
    duplicate_slug = client.post(
        "/store/admin/products",
        data={"csrf_token": csrf, "name": "Test Shim", "price": "1"},
    )
    duplicate_sku = client.post(
        "/store/admin/products",
        data={"csrf_token": csrf, "name": "Again", "sku": "PSV-RFID-001", "price": "1"},
    )
    bad_slug = client.post(
        "/store/admin/products",
        data={"csrf_token": csrf, "name": "Bad", "slug": "Bad Slug", "price": "1"},
    )

    assert created.status_code == 303
    product = _product("test-shim")
    assert product["features"] == ["Spring steel", "Pack of 5"]
    assert product["group_ids"] == {catalog["group"]["id"]}
    assert product["variants"][0]["sku"] is None
    assert product["variants"][0]["upc"] is None
    assert product["variants"][0]["price_cents"] == 950
    assert product["variants"][0]["stock_on_hand"] == 4
    assert duplicate_slug.status_code == 400
    assert "URL slug is already in use" in duplicate_slug.text
    assert duplicate_sku.status_code == 400
    assert "SKU is already in use" in duplicate_sku.text
    assert bad_slug.status_code == 400
    assert "lowercase letters" in bad_slug.text
    assert client.get("/store/product/test-shim").status_code == 200
    assert "Test Shim" in client.get("/store/collection/rfid").text

    variant_url = f"/store/admin/products/{product['id']}/variants"
    added = client.post(
        variant_url,
        data={
            "csrf_token": csrf,
            "sku": "any format/1",
            "name": "Wide",
            "price": "11",
            "stock": "2",
        },
        follow_redirects=False,
    )
    taken = client.post(
        variant_url,
        data={"csrf_token": csrf, "sku": "PSV-RFID-001", "price": "1"},
    )

    assert added.status_code == 303
    variants = _product("test-shim")["variants"]
    assert [v["sku"] for v in variants] == [None, "any format/1"]
    assert variants[1]["position"] == 1
    assert taken.status_code == 400
    assert "SKU is already in use" in taken.text


def test_update_slug_sku_features_and_collections(client, catalog, catalog_factory):
    other = catalog_factory.group(
        catalog_factory.collection("hidden", "Hidden", published=False), "Drafts"
    )
    product = _product()
    csrf = _csrf(client.get(f"/store/admin/products/{product['id']}").text)

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=_variant_form(
            product,
            csrf,
            slug="proxmark-3",
            features="Dual band\nUSB-C",
            group_id=[str(other["id"])],
            variant_sku="",
            variant_upc="012345678905",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = _product("proxmark-3")
    assert updated["features"] == ["Dual band", "USB-C"]
    assert updated["group_ids"] == {other["id"]}
    assert updated["memberships"] == []
    assert updated["variants"][0]["sku"] is None
    assert updated["variants"][0]["upc"] == "012345678905"
    assert client.get("/store/product/proxmark").status_code == 404
    assert client.get("/store/product/proxmark-3").status_code == 200
    assert db.get_collection_by_slug("rfid")["item_count"] == 0
    dashboard = client.get("/store/admin").text
    assert "Hidden › Drafts (hidden)" in dashboard



def test_unpublished_variant_is_retired_from_the_store(client, catalog_factory):
    catalog_factory.product(
        slug="shim-set", name="Shim Set",
        variants=[
            {"name": "Wide", "sku": "SHIM-W", "stock": 2},
            {"name": "Narrow", "sku": "SHIM-N", "stock": 2},
        ],
    )
    product = _product("shim-set")
    wide, narrow = product["variants"]
    csrf = _csrf(client.get(f"/store/admin/products/{product['id']}").text)

    def form(published, version):
        return _variant_form(
            product, csrf,
            version=version,
            variant_id=[str(wide["id"]), str(narrow["id"])],
            variant_name=["Wide", "Narrow"],
            variant_sku=["SHIM-W", "SHIM-N"],
            variant_upc=["", ""],
            variant_price=["25.00", "25.00"],
            variant_stock=["2", "2"],
            variant_expected_stock=["2", "2"],
            variant_published=[str(v["id"]) for v in published],
        )

    response = client.post(
        f"/store/admin/products/{product['id']}",
        data=form([wide], product["updated_at"].isoformat()),
        follow_redirects=False,
    )

    assert response.status_code == 303
    retired = _product("shim-set")
    assert [v["published"] for v in retired["variants"]] == [True, False]
    assert retired["total_stock"] == 2
    admin_page = client.get(f"/store/admin/products/{product['id']}").text
    assert "admin-row-retired" in admin_page and "SHIM-N" in admin_page
    store_page = client.get("/store/product/shim-set").text
    assert "Wide" in store_page and "Narrow" not in store_page
    assert db.search_products("SHIM-N") == []
    _, problems = db.normalize_cart([{"variant_id": narrow["id"], "qty": 1}])
    assert problems == [{"variant_id": narrow["id"], "reason": "unavailable"}]
    with pytest.raises(db.CartUnavailable):
        db.reserve_checkout([{"variant_id": narrow["id"], "qty": 1}])

    # A published product must keep something a shopper can buy.
    last = client.post(
        f"/store/admin/products/{product['id']}",
        data=form([], retired["updated_at"].isoformat()),
    )
    assert last.status_code == 400
    assert "at least one published variant" in last.text
    assert [v["published"] for v in _product("shim-set")["variants"]] == [True, False]

def test_slug_and_sku_conflicts_are_reported(client, catalog_factory):
    catalog_factory.product(
        slug="taken", name="Taken", variants=[{"sku": "TAKEN-1", "stock": 0}]
    )
    product = _product()
    csrf = _csrf(client.get(f"/store/admin/products/{product['id']}").text)
    url = f"/store/admin/products/{product['id']}"

    slug = client.post(url, data=_variant_form(product, csrf, slug="taken"))
    sku = client.post(url, data=_variant_form(product, csrf, variant_sku="TAKEN-1"))
    missing = client.post(url, data=_variant_form(product, csrf, group_id=["999999"]))

    assert slug.status_code == 400
    assert "URL slug is already in use" in slug.text
    assert sku.status_code == 400
    assert "SKU is already in use" in sku.text
    assert missing.status_code == 400
    assert "no longer exists" in missing.text
    assert _product()["variants"][0]["sku"] == "PSV-RFID-001"


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
            "price": "21474836.48",
        },
    )

    assert response.status_code == 400
    assert "less than or equal to 2147483647" in response.text
    assert created.status_code == 400
    with db.connection() as conn:
        assert conn.execute("SELECT 1 FROM products WHERE slug='huge'").fetchone() is None
