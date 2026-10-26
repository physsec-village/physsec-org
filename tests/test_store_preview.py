"""An enabled but unpublished store is an admin-only preview."""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.store import admin_auth
from tests.clerk_sessions import session_token

STOREFRONT_PATHS = (
    "/store",
    "/store/collection/rfid",
    "/store/product/proxmark",
    "/store/search?q=prox",
    "/store/checkout",
    "/store/confirmed?session_id=cs_test",
)


@pytest.fixture(autouse=True)
def unpublished(monkeypatch, catalog_factory):
    monkeypatch.setenv("STORE_PUBLISHED", "false")
    collection = catalog_factory.collection("rfid", "RFID")
    group = catalog_factory.group(collection)
    product = catalog_factory.product(slug="proxmark", name="Proxmark")
    catalog_factory.add(group, product)
    return product


@pytest.fixture
def anonymous():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin(anonymous):
    anonymous.cookies.set(admin_auth.SESSION_COOKIE, session_token())
    return anonymous


@pytest.fixture
def member(anonymous):
    anonymous.cookies.set(
        admin_auth.SESSION_COOKIE, session_token("user_member", admin=False)
    )
    return anonymous


def test_lifespan_reads_the_flag():
    with TestClient(app):
        assert app.state.store_enabled is True
        assert app.state.store_published is False


@pytest.mark.parametrize("path", STOREFRONT_PATHS)
def test_storefront_is_hidden_from_visitors(anonymous, path):
    response = anonymous.get(path)

    assert response.status_code == 404
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["cache-control"] == "no-store"
    assert "<title>Page Not Found" in response.text


def test_cart_and_checkout_apis_are_hidden_from_visitors(anonymous, unpublished):
    payload = {"items": [{"variant_id": unpublished["variants"][0]["id"], "qty": 1}]}

    cart = anonymous.post("/store/api/cart-info", json=payload)
    checkout = anonymous.post("/store/checkout", json=payload)

    assert cart.status_code == 404
    assert checkout.status_code == 404


@pytest.mark.parametrize("path", STOREFRONT_PATHS[:3])
def test_storefront_is_hidden_from_signed_in_non_admins(member, path):
    assert member.get(path).status_code == 404


def test_site_keeps_the_coming_soon_placeholder(anonymous):
    home = anonymous.get("/")
    sitemap = anonymous.get("/sitemap.xml")

    assert '/store">Store</a>' not in home.text
    assert home.text.count('<span class="disabled-state">Soon</span>') == 3
    assert "x-robots-tag" not in home.headers
    assert "<loc>https://physsec.org/store</loc>" not in sitemap.text


def test_admins_preview_the_storefront(admin, unpublished):
    home = admin.get("/store")
    product = admin.get("/store/product/proxmark")
    cart = admin.post(
        "/store/api/cart-info",
        json={"items": [{"variant_id": unpublished["variants"][0]["id"], "qty": 1}]},
    )

    assert home.status_code == 200
    assert "Proxmark" in home.text
    assert "The store is not published yet" in home.text
    assert home.text.count('/store">Store</a>') == 3
    assert "disabled-state" not in home.text
    assert home.headers["x-robots-tag"] == "noindex, nofollow"
    assert home.headers["cache-control"] == "no-store"
    assert product.status_code == 200
    assert cart.status_code == 200


def test_admin_ui_and_webhook_stay_reachable(anonymous, admin):
    login = anonymous.get("/store/admin/login")
    webhook = anonymous.post(
        "/store/webhook", content=b"{}", headers={"stripe-signature": "bad"}
    )
    dashboard = admin.get("/store/admin")

    assert login.status_code == 200
    assert webhook.status_code == 400
    assert dashboard.status_code == 200
    assert "the store is not published" in dashboard.text


def test_published_store_has_no_preview_notice(monkeypatch):
    monkeypatch.setenv("STORE_PUBLISHED", "true")

    with TestClient(app) as client:
        home = client.get("/store")
        dashboard_login = client.get("/store/admin/login")
        sitemap = client.get("/sitemap.xml")

    assert home.status_code == 200
    assert "not published" not in home.text
    assert "x-robots-tag" not in home.headers
    assert "not published" not in dashboard_login.text
    assert "<loc>https://physsec.org/store</loc>" in sitemap.text
