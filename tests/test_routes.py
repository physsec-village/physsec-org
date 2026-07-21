import unittest

from fastapi.testclient import TestClient

from src.main import app


class RouteStatusTests(unittest.TestCase):
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
