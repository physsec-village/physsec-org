import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app
from src.menu import MENU
from src.store import catalog, db, seed, storefront
from src.store.models import BASE_SKU_RE, ProductInput, VariantInput

MENU_ITEMS = [
    item for section in MENU for group in section.groups for item in group.items
]


class StoreCatalogTests(unittest.TestCase):
    def test_every_menu_item_is_in_the_catalog_exactly_once(self):
        expected = {catalog.sku_for(item) for item in MENU_ITEMS}

        self.assertEqual(set(catalog.ITEMS_BY_SKU), expected)
        self.assertEqual(len(catalog.ITEMS), len(expected))
        self.assertEqual(len(catalog.COLLECTIONS), len(MENU))
        for item in catalog.ITEMS:
            with self.subTest(sku=item.sku):
                self.assertRegex(item.sku, BASE_SKU_RE)
                self.assertGreater(item.price_cents, 0)

    def test_placeholder_skus_are_derived_from_menu_codes(self):
        bundle = catalog.ITEMS_BY_CODE["TBD003"]

        self.assertEqual(bundle.sku, "PSV-TBD-003")
        self.assertTrue(bundle.placeholder_sku)
        self.assertEqual(catalog.ITEMS_BY_CODE["BYP012"].upc, "400001012000")

    def test_slugs_are_unique_and_urls_are_stable(self):
        slugs = [item.slug for item in catalog.ITEMS]

        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(
            catalog.ITEMS_BY_CODE["BYP012"].slug, "bypass-measurement-wallet-card"
        )
        self.assertEqual(
            catalog.ITEMS_BY_CODE["BYP014002"].slug, "sc4-schlage-c-keyway-6-pin"
        )

    def test_event_copy_and_footnote_markers_do_not_leak(self):
        event = re.compile(r"DEF CON|\[\^\d+\]")
        for item in catalog.ITEMS:
            for text in (item.name, item.desc, item.note, *item.bullets, *item.details):
                with self.subTest(sku=item.sku, text=text[:40]):
                    self.assertIsNone(event.search(text))
        for collection in catalog.COLLECTIONS:
            self.assertIsNone(event.search(collection.title))
            self.assertIsNone(event.search(collection.blurb))
            for group in collection.groups:
                for text in (group.lede, *group.prose):
                    self.assertIsNone(event.search(text))

    def test_section_price_hints_become_tags_only_when_uniform(self):
        lishi = catalog.COLLECTION_MAP["lishi"]
        elevator = catalog.COLLECTION_MAP["elevator"]

        self.assertEqual(lishi.title, "Lishi Tools")
        self.assertEqual(lishi.tag, "$100 each")
        self.assertEqual(lishi.count, 8)
        # The elevator section says "$10 each" but also sells sets.
        self.assertEqual(elevator.title, "Elevator Keys")
        self.assertEqual(elevator.tag, "")

    def test_every_referenced_footnote_is_kept(self):
        common_set = catalog.ITEMS_BY_CODE["TBD004"]

        self.assertTrue(common_set.restricted)
        self.assertEqual(len(common_set.footnotes), 2)
        self.assertIn(common_set.restricted_reason, common_set.footnotes)
        self.assertTrue(any("$40" in note for note in common_set.footnotes))
        self.assertEqual(catalog.ITEMS_BY_CODE["BYP002"].footnotes, ())

    def test_jump_links_include_table_only_groups(self):
        titles = [g.title for g in catalog.COLLECTION_MAP["elevator"].titled_groups]

        self.assertIn("Quick Reference", titles)
        self.assertNotIn("", titles)

    def test_items_needing_vetting_are_restricted(self):
        restricted = {item.code for item in catalog.ITEMS if item.restricted}

        self.assertEqual(restricted, {"KYS023", "TBD004", "TBD015", "TBD016"})
        self.assertIn("vetted", catalog.ITEMS_BY_CODE["KYS023"].restricted_reason)

    def test_an_item_listed_in_two_sections_is_one_product(self):
        a126 = catalog.ITEMS_BY_CODE["KYS014"]
        placements = [
            group.title
            for collection in catalog.COLLECTIONS
            for group in collection.groups
            if any(item.sku == a126.sku for item in group.items)
        ]

        self.assertEqual(
            placements, ["Common Off-the-Shelf Cam Locks", "Enterphone Keys"]
        )
        self.assertEqual(a126.collection_slug, "keyed-alike")

    def test_related_items_prefer_the_same_group(self):
        x4001 = catalog.ITEMS_BY_CODE["KYS028001"]
        related = catalog.related_items(x4001, limit=3)

        self.assertEqual(
            [item.code for item in related[:2]], ["KYS028002", "KYS028990"]
        )
        self.assertNotIn(x4001, related)

    def test_search_matches_all_terms(self):
        self.assertEqual(
            {item.code for item in catalog.search("latch slip")},
            {"BYP002", "BYP015001", "BYP006"},
        )
        self.assertEqual(catalog.search("   "), ())
        self.assertIn(catalog.ITEMS_BY_CODE["BYP012"], catalog.search("psv-byp-012"))


class StorefrontViewTests(unittest.TestCase):
    def test_money_formats_whole_dollars_without_cents(self):
        self.assertEqual(storefront.money(500), "$5")
        self.assertEqual(storefront.money(1050), "$10.50")

    def test_database_price_and_stock_win_over_the_menu(self):
        item = catalog.ITEMS_BY_CODE["BYP002"]
        front = storefront.Storefront(
            inventory={item.sku: {"price_cents": 650, "available_stock": 2}}
        )
        view = front.view(item)
        missing = front.view(catalog.ITEMS_BY_CODE["BYP006"])

        self.assertEqual(view.price_str, "$6.50")
        self.assertTrue(view.purchasable)
        self.assertFalse(missing.listed)
        self.assertFalse(missing.purchasable)
        self.assertFalse(missing.sold_out)
        self.assertEqual(list(front.browser_catalog()), [item.sku])

    def test_restricted_items_never_reach_the_browser_cart(self):
        feo = catalog.ITEMS_BY_CODE["KYS023"]
        front = storefront.Storefront(
            inventory={feo.sku: {"price_cents": 1000, "available_stock": 5}}
        )

        self.assertFalse(front.view(feo).purchasable)
        self.assertNotIn(feo.sku, front.browser_catalog())


class StoreRouteTests(unittest.TestCase):
    def setUp(self):
        db.require_schema()

    def test_bootstrap_seeds_every_item_and_keeps_restricted_items_unpublished(self):
        self.assertEqual(seed.bootstrap_catalog(), len(catalog.ITEMS))
        self.assertEqual(seed.bootstrap_catalog(), 0)

        inventory = db.sku_inventory()
        self.assertEqual(inventory["PSV-BYP-012"]["price_cents"], 4000)
        self.assertEqual(inventory["PSV-BYP-012"]["available_stock"], 0)
        self.assertNotIn("PSV-KYS-023", inventory)
        self.assertEqual(db.get_product_by_id("PSV-KYS-023")["published"], False)

    def test_bootstrap_reconciles_stale_prices_and_published_restricted_items(self):
        seed.bootstrap_catalog()
        with db.connection(write=True) as conn:
            conn.execute(
                "UPDATE variants SET price_cents=1234,stock_on_hand=7 "
                "WHERE sku='PSV-BYP-012'"
            )
            conn.execute(
                "UPDATE products SET published=true WHERE base_sku='PSV-KYS-023'"
            )
            conn.execute(
                "UPDATE products SET published=false WHERE base_sku='PSV-BYP-002'"
            )

        self.assertEqual(seed.bootstrap_catalog(), 0)

        inventory = db.sku_inventory()
        self.assertEqual(inventory["PSV-BYP-012"]["price_cents"], 4000)
        self.assertEqual(inventory["PSV-BYP-012"]["available_stock"], 7)
        self.assertNotIn("PSV-KYS-023", inventory)
        # Operators may hide items deliberately; bootstrap never re-publishes.
        self.assertNotIn("PSV-BYP-002", inventory)

    def test_restricted_items_are_refused_server_side_even_when_published(self):
        seed.bootstrap_catalog()
        with db.connection(write=True) as conn:
            conn.execute(
                "UPDATE products SET published=true WHERE base_sku='PSV-KYS-023'"
            )
            conn.execute(
                "UPDATE variants SET stock_on_hand=5 "
                "WHERE sku IN ('PSV-KYS-023','PSV-BYP-002')"
            )
        cart = {
            "items": [
                {"sku": "psv-kys-023", "qty": 1},
                {"sku": "PSV-BYP-002", "qty": 1},
            ]
        }
        with TestClient(app) as client:
            checkout = client.post("/store/checkout", json=cart)
            info = client.post("/store/api/cart-info", json=cart)

        self.assertEqual(checkout.status_code, 409)
        self.assertEqual(
            checkout.json()["problems"],
            [{"sku": "PSV-KYS-023", "reason": "restricted"}],
        )
        self.assertEqual(info.json()["items"], [])
        self.assertEqual(
            info.json()["problems"], [{"sku": "PSV-KYS-023", "reason": "restricted"}]
        )
        with db.connection() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM checkouts").fetchone()
        self.assertEqual(count["count"], 0)

    def test_store_pages_render_from_the_menu(self):
        with (
            patch.dict(os.environ, {"STORE_BOOTSTRAP_STOCK": "5"}),
            TestClient(app) as client,
        ):
            home = client.get("/store")
            elevator = client.get("/store/collection/elevator")
            product = client.get("/store/product/bypass-measurement-wallet-card")
            search = client.get("/store/search", params={"q": "latch slip"})
            checkout = client.get("/store/checkout")
            confirmed = client.get("/store/confirmed?session_id=cs_pending")
            legacy = client.get("/store/catalog", follow_redirects=False)

        self.assertEqual(home.status_code, 200)
        self.assertIn("Shop by collection", home.text)
        for collection in catalog.COLLECTIONS:
            self.assertIn(f'href="/store/collection/{collection.slug}"', home.text)
        self.assertNotIn("DEF CON", home.text)

        self.assertEqual(elevator.status_code, 200)
        self.assertIn("MAD Fixtures", elevator.text)
        self.assertIn("Quick Reference", elevator.text)
        self.assertIn('id="mad-fixtures"', elevator.text)
        self.assertIn('href="#quick-reference"', elevator.text)
        self.assertNotIn('class="chip">$10 each', elevator.text)
        self.assertIn("Contact to order", elevator.text)

        self.assertEqual(product.status_code, 200)
        self.assertIn("All 27 functions", product.text)
        self.assertIn("PSV-BYP-012", product.text)
        self.assertIn('data-sku="PSV-BYP-012"', product.text)

        self.assertEqual(search.status_code, 200)
        self.assertIn('class="item-card-name">Keychain Latch Slip', search.text)
        self.assertNotIn('class="item-card-name">Thumbturn', search.text)

        self.assertEqual(checkout.status_code, 200)
        self.assertIn("this site never handles card data", checkout.text)
        self.assertNotIn("Card number", checkout.text)

        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("Payment is processing", confirmed.text)

        self.assertEqual(legacy.status_code, 301)
        self.assertTrue(legacy.headers["location"].endswith("/store"))

    def test_sold_out_and_restricted_items_cannot_be_added(self):
        seed.bootstrap_catalog()
        with TestClient(app) as client:
            product = client.get("/store/product/bare-metal-latch-slip")
            feo = client.get("/store/product/feo-k1")

        self.assertIn("Sold out", product.text)
        self.assertNotIn("data-add", product.text)
        self.assertIn("Vetting required", feo.text)
        self.assertNotIn("data-add", feo.text)
        self.assertNotIn("PSV-KYS-023", feo.text.split('id="psv-catalog"')[1])

    def test_restricted_family_variants_are_refused_too(self):
        db.create_product(
            ProductInput(
                name="FEO-K1 family",
                base_sku="PSV-KYS-023",
                category_label="Keys",
                variants=[
                    VariantInput(sku="PSV-KYS-023-001", price_cents=1000, stock=5)
                ],
            )
        )
        cart = {"items": [{"sku": "PSV-KYS-023-001", "qty": 1}]}
        with TestClient(app) as client:
            checkout = client.post("/store/checkout", json=cart)

        self.assertEqual(checkout.status_code, 409)
        self.assertEqual(
            checkout.json()["problems"],
            [{"sku": "PSV-KYS-023-001", "reason": "restricted"}],
        )

    def test_unknown_pages_return_404(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/store/product/PSV-NOPE-999").status_code, 404)
            self.assertEqual(client.get("/store/collection/nope").status_code, 404)

    def test_search_query_is_escaped_and_bounded(self):
        with TestClient(app) as client:
            response = client.get(
                "/store/search", params={"q": "<script>alert(1)</script>"}
            )
            too_long = client.get("/store/search", params={"q": "x" * 81})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>alert", response.text)
        self.assertEqual(too_long.status_code, 422)

    def test_confirmed_does_not_reflect_an_unknown_session_id(self):
        with TestClient(app) as client:
            response = client.get(
                "/store/confirmed?session_id=<script>alert(1)</script>"
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("alert(", response.text)
        self.assertIn("Payment is processing", response.text)

    def test_store_is_linked_and_in_sitemap(self):
        with TestClient(app) as client:
            home = client.get("/").text
            sitemap = client.get("/sitemap.xml").text

        self.assertIn('/store">Store</a>', home)
        self.assertNotIn("Store coming soon", home)
        self.assertIn("<loc>https://physsec.org/store</loc>", sitemap)
        self.assertIn("<loc>https://physsec.org/store/collection/lishi</loc>", sitemap)
        self.assertNotIn("/store/catalog", sitemap)


if __name__ == "__main__":
    unittest.main()
