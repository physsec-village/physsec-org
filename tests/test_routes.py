import unittest

from fastapi.testclient import TestClient

from src.main import app


class RouteStatusTests(unittest.TestCase):
    def test_accessibility_semantics_are_rendered(self):
        with TestClient(app) as client:
            home = client.get("/").text
            games = client.get("/games").text
            talks = client.get("/talks").text
            volunteer = client.get("/forms/volunteer").text
            contact = client.get("/contact").text
            missing = client.get("/missing").text

        self.assertIn('aria-controls="mobileMenu"', home)
        self.assertIn('aria-expanded="false"', home)
        self.assertIn('id="faq-answer-1" role="region"', home)
        self.assertIn('aria-controls="alarm-levels"', games)
        self.assertIn('<label class="visually-hidden" for="searchInput">', talks)
        self.assertIn('aria-live="polite"', talks)
        self.assertEqual(volunteer.count("<fieldset"), 2)
        self.assertIn('id="volFormError" class="form-error" role="alert"', volunteer)
        self.assertNotIn("alert(", volunteer)
        self.assertIn('id="contactFormError" class="form-error" role="alert"', contact)
        self.assertNotIn("console.log", contact)
        self.assertNotIn("alert(", contact)
        self.assertEqual(missing.count("<main"), 1)

    def test_home_has_search_and_social_metadata(self):
        with TestClient(app) as client:
            response = client.get("/")

        self.assertIn("Physical Security Village | Hands-On Security Education", response.text)
        self.assertIn('<link rel="canonical" href="https://physsec.org/"', response.text)
        self.assertIn('property="og:description"', response.text)

    def test_robots_and_sitemap_are_served(self):
        with TestClient(app) as client:
            robots = client.get("/robots.txt")
            sitemap = client.get("/sitemap.xml")

        self.assertEqual(robots.status_code, 200)
        self.assertIn("Sitemap: https://physsec.org/sitemap.xml", robots.text)
        self.assertEqual(sitemap.status_code, 200)
        self.assertEqual(sitemap.headers["content-type"], "application/xml")
        self.assertIn("<loc>https://physsec.org/forms/volunteer</loc>", sitemap.text)

    def test_missing_page_returns_404(self):
        with TestClient(app) as client:
            response = client.get("/definitely-missing")

        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.headers["content-type"])

    def test_missing_static_file_returns_404(self):
        with TestClient(app) as client:
            response = client.get("/static/definitely-missing.css")

        self.assertEqual(response.status_code, 404)

    def test_game_thumbnails_are_served_locally(self):
        thumbnail_paths = (
            "/static/images/games/slip-thumbnail.webp",
            "/static/images/games/enterphone-thumbnail.webp",
        )
        with TestClient(app) as client:
            for path in thumbnail_paths:
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["content-type"], "image/webp")
