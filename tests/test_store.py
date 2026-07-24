import unittest

from fastapi.testclient import TestClient

from src.main import app
from src.store import catalog


class StoreCatalogTests(unittest.TestCase):
    def test_products_are_built_and_grouped(self):
        self.assertGreater(len(catalog.PRODUCTS), 50)
        cross_key = catalog.PRODUCT_MAP["PSV-BYP-004"]
        self.assertEqual(cross_key.name, "Cross Key")
        self.assertEqual(
            [v.label for v in cross_key.variants], ["Blue", "Black", "Silver"]
        )

    def test_price_overrides_and_hash_prices(self):
        self.assertEqual(catalog.PRODUCT_MAP["PSV-RFID-001"].price, 89.99)
        for product in catalog.PRODUCTS:
            self.assertGreater(product.price, 0)

    def test_featured_and_hero(self):
        self.assertEqual(len(catalog.FEATURED), 4)
        self.assertEqual(catalog.HERO.id, "PSV-RFID-001")


class StoreRouteTests(unittest.TestCase):
    def test_store_pages_render(self):
        with TestClient(app) as client:
            home = client.get("/store")
            cat = client.get("/store/catalog")
            keys = client.get("/store/catalog?cat=KYS")
            product = client.get("/store/product/PSV-BYP-004")
            checkout = client.get("/store/checkout")
            confirmed = client.get("/store/confirmed?order=PSV-123456")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Featured drop", home.text)
        self.assertIn("Shop by Category", home.text)

        self.assertEqual(cat.status_code, 200)
        self.assertIn("All Products", cat.text)
        self.assertIn('id="storeSearch"', cat.text)

        self.assertEqual(keys.status_code, 200)
        self.assertIn("keyed-alike", keys.text)

        self.assertEqual(product.status_code, 200)
        self.assertIn("Cross Key", product.text)
        self.assertIn('id="variantSelect"', product.text)

        self.assertEqual(checkout.status_code, 200)
        self.assertIn("no payment is processed", checkout.text)

        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("PSV-123456", confirmed.text)

    def test_unknown_product_returns_404(self):
        with TestClient(app) as client:
            response = client.get("/store/product/PSV-NOPE-999")

        self.assertEqual(response.status_code, 404)

    def test_confirmed_rejects_malformed_order_number(self):
        with TestClient(app) as client:
            response = client.get("/store/confirmed?order=<script>alert(1)</script>")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("alert(", response.text)
        self.assertIn("Order PSV-", response.text)

    def test_store_is_linked_and_in_sitemap(self):
        with TestClient(app) as client:
            home = client.get("/").text
            sitemap = client.get("/sitemap.xml").text

        self.assertIn('/store">Store</a>', home)
        self.assertNotIn("Store coming soon", home)
        self.assertIn("<loc>https://physsec.org/store</loc>", sitemap)
        self.assertIn("<loc>https://physsec.org/store/catalog</loc>", sitemap)


if __name__ == "__main__":
    unittest.main()
