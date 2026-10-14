import json
import re

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.store import db, storefront


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def catalog(catalog_factory):
    collection = catalog_factory.collection(
        description="First paragraph.\n\nSecond paragraph.", tag="Village tools",
    )
    group = catalog_factory.group(collection, "Entry tools", lede="Practice responsibly.")
    product = catalog_factory.product(
        slug="cross-key", name="Cross Key", description="A compact practice tool.",
        featured=True, features=["Three colours", "Pocket sized"],
        variants=[
            {"name": "Blue", "sku": "opaque.Blue/1", "price_cents": 500, "stock": 0},
            {"name": "Black", "price_cents": 1250, "stock": 4},
        ],
        images=["/static/images/store/byp004.webp"],
    )
    catalog_factory.add(group, product)
    return product, collection, group


def test_home_renders_with_empty_catalog(client):
    response = client.get("/store")
    assert response.status_code == 200
    assert "Store" in response.text
    assert 'data-variant-id=' not in response.text


def test_store_pages_render(client, catalog):
    product, _, _ = catalog
    home = client.get("/store")
    collection = client.get("/store/collection/tools")
    detail = client.get("/store/product/cross-key")
    checkout = client.get("/store/checkout")
    confirmed = client.get("/store/confirmed?session_id=cs_pending")

    assert home.status_code == collection.status_code == detail.status_code == 200
    assert "Village picks" in home.text
    assert "Cross Key" in home.text
    assert '/store/collection/tools' in home.text
    assert "Entry tools" in collection.text
    assert "Practice responsibly." in collection.text
    assert "First paragraph." in collection.text
    assert "Second paragraph." in collection.text
    assert '/static/images/store/byp004.webp' in detail.text
    assert 'id="productVariant"' in detail.text
    assert "Blue" in detail.text and "Black" in detail.text
    assert "Pocket sized" in detail.text
    assert str(product["variants"][1]["id"]) in detail.text
    assert checkout.status_code == 200
    assert "Stripe collects payment" in checkout.text
    assert "Card number" not in checkout.text
    assert confirmed.status_code == 200
    assert "Payment is processing" in confirmed.text


def test_catalog_redirect(client):
    response = client.get("/store/catalog?cat=old", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"].endswith("/store")


def test_empty_collection_and_unassigned_product_render(client, catalog_factory):
    catalog_factory.collection()
    catalog_factory.product()
    assert client.get("/store/collection/tools").status_code == 200
    assert client.get("/store/product/test-tool").status_code == 200


def test_unknown_or_unpublished_pages_return_404(client, catalog_factory):
    catalog_factory.product(published=False)
    catalog_factory.collection(published=False)
    for path in (
        "/store/product/test-tool", "/store/product/missing",
        "/store/collection/tools", "/store/collection/missing",
    ):
        assert client.get(path).status_code == 404


def test_unpublished_product_is_not_shown_or_sellable(client, catalog_factory):
    collection = catalog_factory.collection()
    group = catalog_factory.group(collection)
    hidden = catalog_factory.product(name="Hidden tool", published=False, featured=True)
    catalog_factory.add(group, hidden)
    variant_id = hidden["variants"][0]["id"]
    for path in ("/store", "/store/collection/tools", "/store/search?q=Hidden"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Hidden tool" not in response.text
    payload = {"items": [{"variant_id": variant_id, "qty": 1}]}
    info = client.post("/store/api/cart-info", json=payload)
    assert info.json() == {
        "items": [], "problems": [{"variant_id": variant_id, "reason": "unavailable"}],
    }
    assert client.post("/store/checkout", json=payload).status_code == 409
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS count FROM checkouts").fetchone()["count"] == 0


@pytest.mark.parametrize("query", ["Cross", "compact", "black", "opaque.Blue/1"])
def test_server_side_search(client, catalog, query):
    response = client.get("/store/search", params={"q": query})
    assert response.status_code == 200
    assert 'href="/store/product/cross-key"' in response.text


def test_search_escapes_wildcards(catalog_factory):
    special = catalog_factory.product(slug="special", name="100%_tool\\kit")
    catalog_factory.product(slug="other", name="100anything-tool")
    for query in ("%", "_", "\\", "100%_tool\\"):
        assert [p["id"] for p in db.search_products(query)] == [special["id"]]


def test_collection_order_counts_cover_and_memberships(catalog_factory):
    hidden = catalog_factory.product(slug="hidden", published=False, images=["/hidden.jpg"])
    plain = catalog_factory.product(slug="plain")
    pictured = catalog_factory.product(slug="pictured", images=["/first.jpg", "/second.jpg"])
    later = catalog_factory.collection(slug="later", position=9)
    first = catalog_factory.collection(slug="first", position=1)
    secret = catalog_factory.collection(slug="secret", published=False)
    second_group = catalog_factory.group(first, "Second", position=1)
    first_group = catalog_factory.group(first, "First", position=0)
    secret_group = catalog_factory.group(secret)
    catalog_factory.add(first_group, hidden, position=0)
    catalog_factory.add(first_group, plain, position=1)
    catalog_factory.add(first_group, pictured, position=2)
    catalog_factory.add(second_group, pictured)
    catalog_factory.add(secret_group, pictured)

    collections = db.get_published_collections()
    assert [c["id"] for c in collections] == [first["id"], later["id"]]
    assert collections[0]["item_count"] == 2
    assert collections[0]["cover_url"] == "/first.jpg"
    detail = db.get_collection_by_slug("first")
    assert [g["title"] for g in detail["groups"]] == ["First", "Second"]
    assert [p["id"] for p in detail["groups"][0]["products"]] == [plain["id"], pictured["id"]]
    memberships = db.get_product_by_slug("pictured")["memberships"]
    assert len(memberships) == 2
    assert {m["collection_slug"] for m in memberships} == {"first"}


def test_related_products_rank_group_before_collection(catalog_factory):
    source = catalog_factory.product(slug="source")
    same_collection = catalog_factory.product(slug="collection-peer", name="A collection peer")
    same_group = catalog_factory.product(slug="group-peer", name="Z group peer")
    hidden = catalog_factory.product(slug="hidden", published=False)
    unrelated = catalog_factory.product(slug="unrelated")
    collection = catalog_factory.collection()
    group = catalog_factory.group(collection)
    other_group = catalog_factory.group(collection, "Other")
    for product in (source, same_group, hidden):
        catalog_factory.add(group, product)
    catalog_factory.add(other_group, same_collection)
    catalog_factory.add(other_group, same_group)
    secret = catalog_factory.group(catalog_factory.collection(slug="secret", published=False))
    catalog_factory.add(secret, source)
    catalog_factory.add(secret, unrelated)
    assert [p["id"] for p in db.get_related_products(source["id"])] == [
        same_group["id"], same_collection["id"],
    ]
    assert len(db.get_related_products(source["id"], limit=1)) == 1


def test_price_formatting_and_browser_catalog(catalog):
    product, _, _ = catalog
    view = storefront.get_product(product["slug"])
    assert view.price_str == "From $5"
    assert storefront.money(1250) == "$12.50"
    assert storefront.money(0) == "$0"
    browser = storefront.browser_catalog((view,))
    assert set(browser) == {str(v["id"]) for v in product["variants"]}
    available = browser[str(product["variants"][1]["id"])]
    assert available["price_cents"] == 1250
    assert available["available_stock"] == 4
    assert available["url"] == "/store/product/cross-key"
    assert available["image"] == "/static/images/store/byp004.webp"
    assert "None" not in json.dumps(browser)


def test_sold_out_and_single_variant_product(client, catalog_factory):
    product = catalog_factory.product(variants=[{"stock": 0}])
    view = storefront.get_product(product["slug"])
    assert view.sold_out and not view.purchasable
    response = client.get("/store/product/test-tool")
    assert "Sold out" in response.text
    assert 'id="productVariant"' not in response.text


def test_confirmed_does_not_reflect_unknown_session_id(client):
    response = client.get("/store/confirmed", params={"session_id": "<script>alert(1)</script>"})
    assert response.status_code == 200
    assert "alert(" not in response.text
    assert "Payment is processing" in response.text


def test_store_is_linked_and_in_sitemap(client):
    assert '/store">Store</a>' in client.get("/").text
    sitemap = client.get("/sitemap.xml").text
    assert "<loc>https://physsec.org/store</loc>" in sitemap
    assert "<loc>https://physsec.org/store/catalog</loc>" not in sitemap


def test_in_page_navigation_does_not_use_site_nav(client, catalog):
    for path in ("/store", "/store/collection/tools", "/store/product/cross-key", "/store/search?q=Cross"):
        response = client.get(path)
        assert len(re.findall(r"<nav\b", response.text)) == 1
