import re
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from src.main import app
from src.menu import MENU, Item

ITEMS: list[Item] = [item for s in MENU for g in s.groups for item in g.items]
EXPECTED_SECTION_COUNTS = {
    "Bypass Tools": 11,
    "Covert Instruments": 23,
    "Keys": 73,
    "Other Gear & Swag": 19,
    "Sets": 12,
}
class MenuDataTests(unittest.TestCase):
    def test_every_item_is_priced_and_named(self):
        self.assertEqual(len(ITEMS), sum(EXPECTED_SECTION_COUNTS.values()))
        for item in ITEMS:
            with self.subTest(item=item.name):
                self.assertTrue(item.name.strip())
                self.assertGreater(item.price, 0)
                self.assertTrue(item.code.strip())

    def test_sections_match_the_exported_odoo_categories(self):
        counts = {section.title: len(section.groups[0].items) for section in MENU}
        self.assertEqual(counts, EXPECTED_SECTION_COUNTS)

    def test_barcode_code_is_derived_from_the_sku(self):
        by_sku = {item.sku: item.code for item in ITEMS if item.sku}
        self.assertEqual(by_sku["PSV-KYS-004"], "KYS004")
        self.assertEqual(by_sku["PSV-CVI-009-001"], "CVI009001")
        for item in ITEMS:
            with self.subTest(item=item.name):
                if item.sku:
                    self.assertEqual(item.code, item.sku.removeprefix("PSV-").replace("-", ""))
                else:
                    self.assertTrue(item.code.startswith("ODOO-"))

    def test_codes_are_unique(self):
        codes = [item.code for item in ITEMS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_a_code_maps_to_exactly_one_price(self):
        """Two rows may share a SKU, but never at different prices."""
        prices: dict[str, int] = {}
        for item in ITEMS:
            if item.code in prices:
                with self.subTest(item=item.name):
                    self.assertEqual(prices[item.code], item.price)
            prices[item.code] = item.price

    def test_item_photos_exist_and_are_not_shared(self):
        """A photo filename is derived from the code, so it cannot drift."""
        seen: dict[str, str] = {}
        for item in ITEMS:
            if not item.image:
                continue
            with self.subTest(item=item.name):
                path = Path("static/images/menu") / item.image
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertEqual(item.image, f"{item.code.lower()}.webp")
                self.assertNotIn(item.image, seen, f"also used by {seen.get(item.image)}")
                seen[item.image] = item.name

    def test_photos_are_small_enough_to_ship(self):
        for path in Path("static/images/menu").glob("*.webp"):
            with self.subTest(image=path.name):
                self.assertLess(path.stat().st_size, 40_000)

    def test_section_slugs_are_unique(self):
        slugs = [section.slug for section in MENU]
        self.assertEqual(len(slugs), len(set(slugs)))


class MenuPageTests(unittest.TestCase):
    def test_page_renders_every_item_without_cart_controls(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        self.assertEqual(page.count('<li class="menu-row'), len(ITEMS))
        self.assertNotIn("data-add=", page)
        self.assertNotIn("cartOpen", page)
        self.assertNotIn("cartPanel", page)
        self.assertNotIn("My list", page)

    def test_rows_are_grouped_into_shared_panels_not_one_card_each(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        panels = page.count('<ul class="menu-rows')
        self.assertGreater(panels, 0)
        self.assertLess(panels, len(ITEMS) / 3)

    def test_footnote_markers_become_linked_superscripts(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        # No raw marker may survive to the reader.
        self.assertNotIn("[^", page)
        self.assertNotIn("†", page)

        self.assertNotRegex(page, r'href="#fn-\d+"')
        self.assertNotRegex(page, r'id="fn-\d+"')

    def test_image_labels_are_free_of_footnote_markup(self):
        """The marker must not leak into image alt text."""
        with TestClient(app) as client:
            page = client.get("/menu").text

        for alt in re.findall(r'alt="([^"]*)"', page):
            with self.subTest(alt=alt):
                self.assertNotIn("[^", alt)

    def test_search_asset_is_served(self):
        with TestClient(app) as client:
            for path in (
                "/static/pages/store-menu.js",
            ):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 200)

    def test_page_still_works_without_javascript(self):
        """The price list is server-rendered; JS only adds search."""
        with TestClient(app) as client:
            page = client.get("/menu").text

        for item in ITEMS[:5]:
            with self.subTest(item=item.name):
                self.assertIn(item.name.split(" — ")[0][:20], page)
        self.assertIn("$200", page)
