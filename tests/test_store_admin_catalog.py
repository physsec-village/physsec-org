"""Store admin: editing the whole catalog, images and the Stripe ledger."""

import re

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.store import db, media

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def client():
    with TestClient(app) as anonymous:
        page = anonymous.get("/store/admin/login")
        response = anonymous.post(
            "/store/admin/login",
            data={"csrf_token": _csrf(page.text), "username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        yield anonymous


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "MEDIA_DIR", str(tmp_path))
    return tmp_path


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page)
    assert match, "form has no CSRF token"
    return match.group(1)


def _version(page: str) -> str:
    match = re.search(r'name="version" value="([^"]+)"', page)
    assert match, "form has no version"
    return match.group(1)


def _collection_form(collection: dict, csrf: str, **overrides) -> dict:
    form = {
        "csrf_token": csrf,
        "title": collection["title"],
        "slug": collection["slug"],
        "tag": collection["tag"],
        "blurb": collection["blurb"],
        "description": collection["description"],
        "published": "true" if collection["published"] else "",
        "version": collection["updated_at"].isoformat(),
        "group_row_id": [str(g["id"]) for g in collection["groups"]],
        "group_title": [g["title"] for g in collection["groups"]],
        "group_tag": [g["tag"] for g in collection["groups"]],
        "group_lede": [g["lede"] for g in collection["groups"]],
    }
    form.update(overrides)
    if not form["published"]:
        del form["published"]
    return form


def _product_form(product: dict, csrf: str, **overrides) -> dict:
    form = {
        "csrf_token": csrf,
        "name": product["name"],
        "slug": product["slug"],
        "description": product["description"],
        "features": "\n".join(product["features"]),
        "group_id": [str(group_id) for group_id in product["group_ids"]],
        "published": "true",
        "version": product["updated_at"].isoformat(),
        "variant_id": [str(v["id"]) for v in product["variants"]],
        "variant_name": [v["name"] for v in product["variants"]],
        "variant_sku": [v["sku"] or "" for v in product["variants"]],
        "variant_upc": [v["upc"] or "" for v in product["variants"]],
        "variant_price": ["10.00" for _ in product["variants"]],
        "variant_stock": [str(v["stock_on_hand"]) for v in product["variants"]],
        "variant_expected_stock": [str(v["stock_on_hand"]) for v in product["variants"]],
        "variant_published": [str(v["id"]) for v in product["variants"] if v["published"]],
        "image_id": [str(i["id"]) for i in product["images"]],
        "image_alt": [i["alt"] for i in product["images"]],
    }
    form.update(overrides)
    return form


def _product(slug: str) -> dict:
    with db.connection() as conn:
        row = conn.execute("SELECT id FROM products WHERE slug=%s", (slug,)).fetchone()
    assert row is not None
    return db.admin_product(row["id"])


# Collections.
def test_collection_pages_create_edit_reorder_and_delete(client, catalog_factory):
    first = catalog_factory.collection("first", "First", position=0)
    catalog_factory.collection("second", "Second", position=1)
    listing = client.get("/store/admin/collections")
    csrf = _csrf(listing.text)
    assert listing.status_code == 200
    assert listing.text.index("First") < listing.text.index("Second")

    created = client.post(
        "/store/admin/collections",
        data={"csrf_token": csrf, "title": "Swag & Gear", "tag": "New", "published": "true"},
        follow_redirects=False,
    )
    duplicate = client.post(
        "/store/admin/collections",
        data={"csrf_token": csrf, "title": "Other", "slug": "first"},
    )
    blank = client.post("/store/admin/collections", data={"csrf_token": csrf, "title": " "})

    assert created.status_code == 303
    collection_id = int(created.headers["location"].split("/collections/")[1].split("?")[0])
    collection = db.admin_collection(collection_id)
    assert collection["slug"] == "swag-gear"
    assert collection["position"] == 2
    assert len(collection["groups"]) == 1 and collection["groups"][0]["title"] == ""
    assert duplicate.status_code == 400 and "slug is already in use" in duplicate.text
    assert blank.status_code == 400 and "title is required" in blank.text
    assert client.get("/store/collection/swag-gear").status_code == 200

    moved = client.post(
        f"/store/admin/collections/{collection_id}/move",
        data={"csrf_token": csrf, "direction": "up"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert [c["slug"] for c in db.admin_collections()] == ["first", "swag-gear", "second"]
    sideways = client.post(
        f"/store/admin/collections/{collection_id}/move",
        data={"csrf_token": csrf, "direction": "sideways"},
    )
    assert sideways.status_code == 400 and "Unknown direction" in sideways.text

    page = client.get(f"/store/admin/collections/{collection_id}")
    assert page.status_code == 200
    saved = client.post(
        f"/store/admin/collections/{collection_id}",
        data=_collection_form(
            collection,
            csrf,
            title="Swag",
            slug="swag",
            description="Para one.\n\nPara two.",
            group_title=["Shirts"],
            published="",
        ),
        follow_redirects=False,
    )
    assert saved.status_code == 303
    updated = db.admin_collection(collection_id)
    assert (updated["title"], updated["slug"], updated["published"]) == ("Swag", "swag", False)
    assert updated["description"] == "Para one.\n\nPara two."
    assert updated["groups"][0]["title"] == "Shirts"
    assert client.get("/store/collection/swag").status_code == 404

    stale = client.post(
        f"/store/admin/collections/{collection_id}",
        data=_collection_form(collection, csrf, title="Old tab"),
    )
    assert stale.status_code == 400 and "changed after you loaded" in stale.text
    assert db.admin_collection(collection_id)["title"] == "Swag"

    foreign = client.post(
        f"/store/admin/collections/{collection_id}",
        data=_collection_form(updated, csrf, group_row_id=["999999"]),
    )
    assert foreign.status_code == 400 and "does not belong" in foreign.text

    deleted = client.post(
        f"/store/admin/collections/{collection_id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert db.admin_collection(collection_id) is None
    assert client.get(f"/store/admin/collections/{collection_id}").status_code == 404
    assert client.get(f"/store/admin/collections/{first['id']}").status_code == 200


def test_groups_and_items_are_managed_from_the_collection_page(client, catalog_factory):
    collection = catalog_factory.collection("tools", "Tools")
    group = catalog_factory.group(collection, "Entry", position=0)
    shim = catalog_factory.product("shim", "Shim")
    pick = catalog_factory.product("pick", "Pick", published=False)
    catalog_factory.add(group, shim)
    base = f"/store/admin/collections/{collection['id']}"
    csrf = _csrf(client.get(base).text)

    added_group = client.post(
        f"{base}/groups",
        data={"csrf_token": csrf, "title": "Decoding", "lede": "Read the lock."},
        follow_redirects=False,
    )
    assert added_group.status_code == 303
    groups = db.admin_collection(collection["id"])["groups"]
    assert [g["title"] for g in groups] == ["Entry", "Decoding"]
    assert groups[1]["position"] == 1
    decoding = groups[1]

    moved_group = client.post(
        f"{base}/groups/{decoding['id']}/move",
        data={"csrf_token": csrf, "direction": "up"},
        follow_redirects=False,
    )
    assert moved_group.status_code == 303
    assert [g["title"] for g in db.admin_collection(collection["id"])["groups"]] == [
        "Decoding", "Entry",
    ]

    added = client.post(
        f"{base}/groups/{group['id']}/items",
        data={"csrf_token": csrf, "product_id": str(pick["id"])},
        follow_redirects=False,
    )
    again = client.post(
        f"{base}/groups/{group['id']}/items",
        data={"csrf_token": csrf, "product_id": str(pick["id"])},
        follow_redirects=False,
    )
    missing = client.post(
        f"{base}/groups/{group['id']}/items",
        data={"csrf_token": csrf, "product_id": "999999"},
    )
    assert added.status_code == again.status_code == 303
    assert missing.status_code == 400 and "Product not found" in missing.text
    entry = next(
        g for g in db.admin_collection(collection["id"])["groups"] if g["id"] == group["id"]
    )
    assert [p["slug"] for p in entry["products"]] == ["shim", "pick"]
    assert client.get("/store/collection/tools").text.count("Pick") == 0  # hidden product

    moved = client.post(
        f"{base}/groups/{group['id']}/items/{pick['id']}/move",
        data={"csrf_token": csrf, "direction": "up"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    entry = next(
        g for g in db.admin_collection(collection["id"])["groups"] if g["id"] == group["id"]
    )
    assert [p["slug"] for p in entry["products"]] == ["pick", "shim"]
    page = client.get(base).text
    assert page.index("/pick") < page.index("/shim")
    # Each group's picker leaves out the products already in that group, so
    # the pick is offered once (by Decoding) and the shim once as well.
    assert page.count('<option value="%d">' % pick["id"]) == 1
    assert page.count('<option value="%d">' % shim["id"]) == 1

    removed = client.post(
        f"{base}/groups/{group['id']}/items/{pick['id']}/remove",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert db.admin_product(pick["id"])["group_ids"] == set()

    other = catalog_factory.collection("other", "Other")
    foreign = client.post(
        f"{base}/groups/{catalog_factory.group(other)['id']}/delete",
        data={"csrf_token": csrf},
    )
    assert foreign.status_code == 400 and "Group not found" in foreign.text

    deleted = client.post(
        f"{base}/groups/{group['id']}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert [g["title"] for g in db.admin_collection(collection["id"])["groups"]] == ["Decoding"]
    assert db.admin_product(shim["id"])["published"] is True
    assert client.get("/store/product/shim").status_code == 200


# Products: variants, deletion and the dashboard filters.
def test_variants_can_be_reordered_and_deleted_until_sold(client, catalog_factory):
    product = catalog_factory.product(
        "shim-set", "Shim Set",
        variants=[{"name": "Wide", "sku": "W"}, {"name": "Narrow", "sku": "N"}],
    )
    wide, narrow = product["variants"]
    base = f"/store/admin/products/{product['id']}"
    page = client.get(base)
    csrf = _csrf(page.text)
    loaded_version = _version(page.text)

    moved = client.post(
        f"{base}/variants/{narrow['id']}/move",
        data={"csrf_token": csrf, "direction": "up"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    current = _product("shim-set")
    assert [v["name"] for v in current["variants"]] == ["Narrow", "Wide"]
    assert [v["position"] for v in current["variants"]] == [0, 1]
    # Moving a variant counts as an edit, so an older form is now stale.
    assert current["updated_at"].isoformat() != loaded_version
    assert "Narrow" in client.get("/store/product/shim-set").text

    db.reserve_checkout([{"variant_id": wide["id"], "qty": 1}])
    sold = client.post(f"{base}/variants/{wide['id']}/delete", data={"csrf_token": csrf})
    assert sold.status_code == 400
    assert "reserved or sold" in sold.text
    assert len(_product("shim-set")["variants"]) == 2

    deleted = client.post(
        f"{base}/variants/{narrow['id']}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert [v["name"] for v in _product("shim-set")["variants"]] == ["Wide"]

    last = client.post(f"{base}/variants/{wide['id']}/delete", data={"csrf_token": csrf})
    assert last.status_code == 400 and "at least one variant" in last.text

    blocked = client.post(f"{base}/delete", data={"csrf_token": csrf})
    assert blocked.status_code == 400 and "cannot be deleted" in blocked.text
    assert client.get(base).status_code == 200


def test_deleting_an_unsold_product_removes_it_and_its_uploads(
    client, catalog_factory, media_dir
):
    group = catalog_factory.group(catalog_factory.collection())
    product = catalog_factory.product("draft", "Draft", variants=[{}, {"name": "B"}])
    catalog_factory.add(group, product)
    upload = media.save_image(PNG)
    assert (media_dir / "store" / upload.rsplit("/", 1)[1]).exists()
    db.add_image(product["id"], upload, "Draft")
    db.add_image(product["id"], "/static/images/store/kys001.webp", "Stock photo")
    csrf = _csrf(client.get(f"/store/admin/products/{product['id']}").text)

    deleted = client.post(
        f"/store/admin/products/{product['id']}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert deleted.status_code == 303
    assert deleted.headers["location"].endswith("/store/admin?notice=deleted")
    assert db.admin_product(product["id"]) is None
    assert not (media_dir / "store" / upload.rsplit("/", 1)[1]).exists()
    assert db.get_collection_by_slug("tools")["item_count"] == 0
    assert client.get(f"/store/admin/products/{product['id']}").status_code == 404


def test_dashboard_search_and_status_filters(client, catalog_factory):
    catalog_factory.product("live", "Live Pick", variants=[{"sku": "LP-1", "stock": 2}])
    catalog_factory.product("gone", "Sold Out Shim", variants=[{"stock": 0}])
    catalog_factory.product("draft", "Hidden Draft", published=False)
    group = catalog_factory.group(catalog_factory.collection())
    catalog_factory.add(group, _product("live"))

    def names(query):
        page = client.get(f"/store/admin?{query}")
        assert page.status_code == 200
        return re.findall(r'/store/admin/products/\d+">([^<]+)</a>', page.text)

    assert names("q=lp-1") == ["Live Pick"]
    assert names("q=shim") == ["Sold Out Shim"]
    assert names("status=hidden") == ["Hidden Draft"]
    assert names("status=sold_out") == ["Sold Out Shim"]
    assert names("status=unlisted") == ["Hidden Draft", "Sold Out Shim"]
    assert names("status=bogus") == ["Hidden Draft", "Live Pick", "Sold Out Shim"]
    assert names("q=nothing-matches") == []
    assert "No products match." in client.get("/store/admin?q=nothing-matches").text


# Images.
def test_images_are_uploaded_captioned_reordered_and_removed(
    client, catalog_factory, media_dir
):
    product = catalog_factory.product("key", "Key")
    base = f"/store/admin/products/{product['id']}"
    csrf = _csrf(client.get(base).text)

    uploaded = client.post(
        f"{base}/images",
        data={"csrf_token": csrf, "alt": "  A   key "},
        files={"image": ("photo.exe", PNG, "application/octet-stream")},
        follow_redirects=False,
    )
    linked = client.post(
        f"{base}/images",
        data={"csrf_token": csrf, "url": "/static/images/store/kys001.webp", "alt": "Stock"},
        follow_redirects=False,
    )
    not_image = client.post(
        f"{base}/images",
        data={"csrf_token": csrf},
        files={"image": ("photo.png", b"<svg onload=alert(1)>", "image/png")},
    )
    too_big = client.post(
        f"{base}/images",
        data={"csrf_token": csrf},
        files={"image": ("big.png", PNG + b"\0" * media.MAX_IMAGE_BYTES, "image/png")},
    )
    empty = client.post(f"{base}/images", data={"csrf_token": csrf})
    bad_url = client.post(
        f"{base}/images", data={"csrf_token": csrf, "url": "javascript:alert(1)"}
    )
    scheme_relative = client.post(
        f"{base}/images", data={"csrf_token": csrf, "url": "//evil.example/x.png"}
    )

    assert uploaded.status_code == linked.status_code == 303
    assert not_image.status_code == 400 and "WebP, PNG, JPEG or GIF" in not_image.text
    assert too_big.status_code == 400 and "5 MB" in too_big.text
    assert empty.status_code == 400 and "Upload an image file" in empty.text
    assert bad_url.status_code == 400 and "start with /" in bad_url.text
    assert scheme_relative.status_code == 400
    images = _product("key")["images"]
    assert [i["alt"] for i in images] == ["A key", "Stock"]
    assert images[0]["url"].startswith("/media/store/") and images[0]["url"].endswith(".png")
    assert [i["position"] for i in images] == [0, 1]
    stored = media_dir / "store" / images[0]["url"].rsplit("/", 1)[1]
    assert stored.read_bytes() == PNG
    assert len(list((media_dir / "store").iterdir())) == 1  # rejected uploads leave no files
    assert images[0]["url"] in client.get("/store/product/key").text

    product = _product("key")
    captioned = client.post(
        base,
        data=_product_form(product, csrf, image_alt=["Brass key", "Stock photo"]),
        follow_redirects=False,
    )
    assert captioned.status_code == 303
    assert [i["alt"] for i in _product("key")["images"]] == ["Brass key", "Stock photo"]
    foreign = client.post(
        base,
        data=_product_form(_product("key"), csrf, image_id=["999999", str(images[1]["id"])]),
    )
    assert foreign.status_code == 400 and "does not belong" in foreign.text

    moved = client.post(
        f"{base}/images/{images[1]['id']}/move",
        data={"csrf_token": csrf, "direction": "up"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert [i["alt"] for i in _product("key")["images"]] == ["Stock photo", "Brass key"]
    assert 'src="/static/images/store/kys001.webp"' in client.get("/store").text

    removed = client.post(
        f"{base}/images/{images[0]['id']}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert [i["alt"] for i in _product("key")["images"]] == ["Stock photo"]
    assert not stored.exists()
    missing = client.post(f"{base}/images/{images[0]['id']}/delete", data={"csrf_token": csrf})
    assert missing.status_code == 400 and "Image not found" in missing.text


def test_shared_upload_survives_removal_from_one_product(catalog_factory, media_dir):
    first = catalog_factory.product("one", "One")
    second = catalog_factory.product("two", "Two")
    upload = media.save_image(PNG)
    db.add_image(first["id"], upload, "")
    db.add_image(second["id"], upload, "")
    first_image = db.admin_product(first["id"])["images"][0]

    assert db.delete_image(first["id"], first_image["id"]) is None
    second_image = db.admin_product(second["id"])["images"][0]
    assert db.delete_image(second["id"], second_image["id"]) == upload


def test_media_helpers_only_touch_their_own_files(media_dir):
    outside = media_dir / "keep.txt"
    outside.write_text("keep")
    media.remove_image("/static/images/store/kys001.webp")
    media.remove_image("/media/store/../keep.txt")
    media.remove_image("/media/store/")
    assert outside.exists()
    assert media.image_extension(b"RIFF\0\0\0\0WEBPVP8 ") == "webp"
    assert media.image_extension(b"GIF89a") == "gif"
    assert media.image_extension(b"\xff\xd8\xff\xe0") == "jpg"
    assert media.image_extension(b"<svg") is None
    with pytest.raises(media.MediaError):
        media.save_image(b"")
    with pytest.raises(media.MediaError):
        media.image_url("x" * (media.MAX_URL_LENGTH + 1))
    assert media.image_url(" https://cdn.example/a.webp ") == "https://cdn.example/a.webp"


# Orders and Stripe.
def test_orders_filter_by_review_and_link_to_stripe(client, catalog_factory, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    variant_id = catalog_factory.product(variants=[{"stock": 1}])["variants"][0]["id"]
    checkout = db.reserve_checkout([{"variant_id": variant_id, "qty": 1}])
    order_id = db.process_paid_event(
        "evt_paid",
        {
            "id": "cs_paid",
            "metadata": {"checkout_id": checkout["id"]},
            "payment_status": "paid",
            "payment_intent": "pi_123",
            "currency": "usd",
            "amount_subtotal": checkout["subtotal_cents"],
            "amount_total": checkout["subtotal_cents"],
        },
    )
    assert db.process_dispute_event(
        "evt_dispute", {"id": "dp_1", "payment_intent": "pi_123", "reason": "fraudulent"}
    ) == "needs_review"
    assert db.process_dispute_event("evt_dispute", {"id": "dp_1", "payment_intent": "pi_123"}) == "duplicate"

    flagged = client.get("/store/admin/orders?review=needs_review")
    clear = client.get("/store/admin/orders?review=clear")
    detail = client.get(f"/store/admin/orders/{order_id}")
    dashboard = client.get("/store/admin")

    assert order_id[:8] in flagged.text
    assert order_id[:8] not in clear.text
    assert "https://dashboard.stripe.com/test/payments/pi_123" in detail.text
    assert "Payment disputed in Stripe (fraudulent)" in detail.text
    assert re.search(
        r'admin-stat-value">1</span>\s*<span class="admin-stat-label">Orders needing review',
        dashboard.text,
    )

    with pytest.raises(db.CheckoutConflict, match="before its order"):
        db.process_dispute_event("evt_orphan", {"id": "dp_2", "payment_intent": "pi_none"})
    with pytest.raises(db.CheckoutConflict, match="lacks payment intent"):
        db.process_dispute_event("evt_bare", {"id": "dp_3"})


def test_stripe_page_reports_configuration_and_events(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_123")
    monkeypatch.setenv("STORE_PUBLIC_ORIGIN", "https://physsec.org/")
    db.process_ignored_event("evt_ignored", "payment_intent.created", object_id="pi_x")
    db.record_event_failure(
        "evt_failed", "charge.refunded", "checkout_conflict", "Refund arrived before its order.",
        object_id="ch_x",
    )

    page = client.get("/store/admin/stripe")

    assert page.status_code == 200
    assert "https://physsec.org/store/webhook" in page.text
    assert "https://dashboard.stripe.com/payments" in page.text
    assert "sk_live_123" not in page.text and "whsec_123" not in page.text
    assert "Live" in page.text
    assert "payment_intent.created" in page.text
    assert "Refund arrived before its order." in page.text
    summary = db.admin_stripe_summary()
    assert (summary["ignored"], summary["failed"], summary["received"]) == (1, 1, 2)
    assert summary["last_received_at"] is not None

    monkeypatch.delenv("STRIPE_SECRET_KEY")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    bare = client.get("/store/admin/stripe")
    assert "Not configured" in bare.text and "Webhooks are rejected." in bare.text
