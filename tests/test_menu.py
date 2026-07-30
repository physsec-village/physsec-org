import csv
import re
import unittest

from fastapi.testclient import TestClient

from src.main import app
from src.menu import MENU, Item

ITEMS: list[Item] = [item for s in MENU for g in s.groups for item in g.items]
SKU_PATTERN = re.compile(r"^PSV-[A-Z]+-\d{3}(-\d{3})?$")


def store_skus() -> set[str]:
    with open("src/store/products.tsv") as fh:
        return {row[1] for row in csv.reader(fh, delimiter="\t") if len(row) >= 2}


class MenuDataTests(unittest.TestCase):
    def test_every_item_is_priced_and_named(self):
        self.assertGreater(len(ITEMS), 50)
        for item in ITEMS:
            with self.subTest(item=item.name):
                self.assertTrue(item.name.strip())
                self.assertGreater(item.price, 0)
                self.assertTrue(item.code.strip())

    def test_real_skus_exist_in_the_store_catalogue(self):
        """A code the register scans must resolve to a real product."""
        known = store_skus()
        for item in ITEMS:
            if item.sku is None:
                continue
            with self.subTest(item=item.name):
                self.assertRegex(item.sku, SKU_PATTERN)
                self.assertIn(item.sku, known)

    def test_barcode_code_is_derived_from_the_sku(self):
        for item in ITEMS:
            with self.subTest(item=item.name):
                if item.sku:
                    self.assertEqual(item.code, item.sku.removeprefix("PSV-").replace("-", ""))
                else:
                    self.assertTrue(item.code.startswith("TBD"))

    def test_codes_stay_short_enough_for_a_low_density_symbol(self):
        for item in ITEMS:
            with self.subTest(item=item.name):
                self.assertLessEqual(len(item.code), 10)

    def test_a_code_maps_to_exactly_one_price(self):
        """Two rows may share a SKU, but never at different prices."""
        prices: dict[str, int] = {}
        for item in ITEMS:
            if item.code in prices:
                with self.subTest(item=item.name):
                    self.assertEqual(prices[item.code], item.price)
            prices[item.code] = item.price

    def test_section_slugs_are_unique(self):
        slugs = [section.slug for section in MENU]
        self.assertEqual(len(slugs), len(set(slugs)))


class MenuPageTests(unittest.TestCase):
    def test_page_renders_every_item_with_add_controls(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        self.assertEqual(page.count('<li class="menu-row'), len(ITEMS))
        for item in ITEMS:
            with self.subTest(item=item.name):
                self.assertIn(f'data-add="{item.code}"', page)

    def test_rows_are_grouped_into_shared_panels_not_one_card_each(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        panels = page.count('<ul class="menu-rows">')
        self.assertGreater(panels, 0)
        self.assertLess(panels, len(ITEMS) / 3)

    def test_cart_assets_are_served(self):
        with TestClient(app) as client:
            for path in ("/static/pages/store-menu.js", "/static/pages/qr.js"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 200)

    def test_page_still_works_without_javascript(self):
        """The price list is server-rendered; JS only adds search and the list."""
        with TestClient(app) as client:
            page = client.get("/menu").text

        for item in ITEMS[:5]:
            with self.subTest(item=item.name):
                self.assertIn(item.name.split(" — ")[0][:20], page)
        self.assertIn("$180", page)
