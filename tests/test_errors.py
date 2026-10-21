import logging
import re
from unittest.mock import patch

import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from src.main import app

SECRET = "leaked-internal-detail SELECT * FROM store.checkouts"
BROWSER_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8"
)
STRIPE_ACCEPT = "*/*; q=0.5, application/xml"


@pytest.fixture
def client():
    """A test client that returns server errors instead of raising them.

    Starlette re-raises after sending the 500, so the test client must not
    turn the exception back into a test failure.
    """
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_json_500(response, records):
    """Assert a JSON 500 body and return the matching log record."""
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"detail", "error_id"}
    assert body["detail"] == "Internal server error."
    return assert_logged_500(response, records, body["error_id"])


def assert_html_500(response, records):
    """Assert an HTML 500 page showing the logged error_id and return its record."""
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    [record] = [r for r in records if r.getMessage().startswith("unhandled_exception ")]
    error_id = re.search(r"error_id=([0-9a-f]{32}) ", record.getMessage()).group(1)
    assert error_id in response.text
    return assert_logged_500(response, records, error_id)


def assert_logged_500(response, records, error_id):
    """Assert no-store headers, no leaked internals, and one logged traceback."""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Accept"
    assert SECRET not in response.text
    assert "Traceback" not in response.text

    matching = [
        record
        for record in records
        if record.getMessage().startswith(f"unhandled_exception error_id={error_id} ")
    ]
    assert len(matching) == 1
    assert matching[0].levelno == logging.ERROR
    assert matching[0].exc_info is not None
    return matching[0]


def test_unhandled_route_exception_returns_json_and_logs_error_id(client, caplog):
    """A route exception logs method, path without query, and traceback."""
    with patch(
        "src.router.templates.TemplateResponse", side_effect=RuntimeError(SECRET)
    ):
        response = client.get("/about?session_id=cs_test_secret")

    record = assert_json_500(response, caplog.records)
    message = record.getMessage()
    assert "method=GET" in message
    assert "path='/about'" in message
    assert "cs_test_secret" not in message
    assert isinstance(record.exc_info[1], RuntimeError)
    assert SECRET in caplog.text  # the traceback is logged, not just returned away


def test_unhandled_exception_in_store_route_returns_json(client, caplog):
    """Store routes are covered by the app-wide handler."""
    with patch("src.store.router.storefront.products", side_effect=KeyError(SECRET)):
        response = client.get("/store")

    assert_json_500(response, caplog.records)


def test_unhandled_exception_in_static_mount_returns_json(client, caplog):
    """Mounted StaticFiles apps are covered by the app-wide handler."""
    with patch.object(StaticFiles, "get_response", side_effect=OSError(SECRET)):
        response = client.get("/static/does-not-matter.css")

    assert_json_500(response, caplog.records)


def test_unhandled_exception_in_404_handler_returns_json(client, caplog):
    """A failure inside another exception handler still gets a 500."""
    with patch("src.router.templates.TemplateResponse", side_effect=ValueError(SECRET)):
        response = client.get("/definitely-missing")

    assert_json_500(response, caplog.records)


def test_each_error_gets_a_distinct_id(client):
    """Each failed request gets its own error_id."""
    with patch("src.router.templates.TemplateResponse", side_effect=RuntimeError()):
        first = client.get("/about").json()["error_id"]
        second = client.get("/about").json()["error_id"]

    assert first != second


def test_existing_error_responses_are_unchanged(client):
    """The 404 page, 422 errors, and HTTPException responses keep their format."""
    missing = client.get("/definitely-missing")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")

    invalid = client.post("/store/api/cart-info", json={"items": "not-a-list"})
    assert invalid.status_code == 422
    assert "error_id" not in invalid.json()
    assert isinstance(invalid.json()["detail"], list)

    with patch("src.store.router.storefront.products", return_value=[]):
        unavailable = client.get("/store")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Store catalog is unavailable."}


def test_stripe_style_client_gets_json(client, caplog):
    """Stripe's Accept header gets JSON rather than the HTML page."""
    with patch("src.store.router.storefront.products", side_effect=KeyError(SECRET)):
        response = client.get("/store", headers={"Accept": STRIPE_ACCEPT})

    assert_json_500(response, caplog.records)


def test_browser_gets_html_error_page(client, caplog):
    """A browser's Accept header gets the full HTML 500 page."""
    with patch("src.store.router.storefront.products", side_effect=KeyError(SECRET)):
        response = client.get("/store", headers={"Accept": BROWSER_ACCEPT})

    assert_html_500(response, caplog.records)
    assert "Something Went Wrong" in response.text
    assert 'class="site-nav-shell"' in response.text  # rendered from base.html


def test_browser_gets_fallback_page_when_error_template_fails(client, caplog):
    """A broken 500 template falls back to the static page and is logged."""
    with patch("src.router.templates.TemplateResponse", side_effect=RuntimeError(SECRET)):
        response = client.get("/about", headers={"Accept": BROWSER_ACCEPT})

    record = assert_html_500(response, caplog.records)
    error_id = re.search(r"error_id=(\w+) ", record.getMessage()).group(1)
    assert f"Reference: {error_id}" in response.text
    assert any(
        r.getMessage() == f"error_page_render_failed error_id={error_id}"
        for r in caplog.records
    )


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        (BROWSER_ACCEPT, "text/html"),
        ("text/html", "text/html"),
        ("text/html;q=0.9, application/json;q=0.5", "text/html"),
        (STRIPE_ACCEPT, "application/json"),
        ("*/*", "application/json"),
        ("", "application/json"),
        ("application/json, text/html;q=0", "application/json"),
        ("application/json, text/html", "application/json"),
        ("text/html;q=0.5, application/json", "application/json"),
        ("text/html;q=0.5, application/*", "application/json"),
        ("text/html;q=bogus", "application/json"),
    ],
)
def test_error_format_follows_accept_preferences(client, accept, expected):
    """HTML is chosen only when text/html is strictly preferred over JSON."""
    with patch.object(StaticFiles, "get_response", side_effect=OSError(SECRET)):
        response = client.get("/static/x.css", headers={"Accept": accept})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(expected)
