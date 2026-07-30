import csv
import re
from pathlib import Path
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

    def test_no_orphaned_photos(self):
        referenced = {i.image for i in ITEMS if i.image}
        on_disk = {p.name for p in Path("static/images/menu").glob("*")}
        self.assertEqual(on_disk - referenced, set())

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

    def test_footnote_markers_become_linked_superscripts(self):
        with TestClient(app) as client:
            page = client.get("/menu").text

        # No raw marker may survive to the reader.
        self.assertNotIn("[^", page)
        self.assertNotIn("†", page)

        referenced = set(re.findall(r'href="#fn-(\d+)"', page))
        defined = set(re.findall(r'id="fn-(\d+)"', page))
        self.assertTrue(referenced, "expected at least one footnote reference")
        self.assertEqual(referenced - defined, set(), "reference with no footnote")
        self.assertEqual(defined - referenced, set(), "footnote nothing points at")

    def test_cart_labels_are_free_of_footnote_markup(self):
        """The marker must not leak into the cart or the image alt text."""
        with TestClient(app) as client:
            page = client.get("/menu").text

        for attribute in re.findall(r'data-name="([^"]*)"', page):
            with self.subTest(attribute=attribute):
                self.assertNotIn("[^", attribute)
        for alt in re.findall(r'alt="([^"]*)"', page):
            with self.subTest(alt=alt):
                self.assertNotIn("[^", alt)

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
