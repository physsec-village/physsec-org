import logging
from unittest.mock import patch

import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from src.main import app

SECRET = "leaked-internal-detail SELECT * FROM store.checkouts"


@pytest.fixture
def client():
    # Starlette re-raises after sending the 500, so the test client must not
    # turn the exception back into a test failure.
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_json_500(response, records):
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"detail", "error_id"}
    assert body["detail"] == "Internal server error."
    assert SECRET not in response.text
    assert "Traceback" not in response.text

    matching = [record for record in records if body["error_id"] in record.getMessage()]
    assert len(matching) == 1
    assert matching[0].levelno == logging.ERROR
    assert matching[0].exc_info is not None
    return matching[0]


def test_unhandled_route_exception_returns_json_and_logs_error_id(client, caplog):
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
    with patch("src.store.router.storefront.products", side_effect=KeyError(SECRET)):
        response = client.get("/store")

    assert_json_500(response, caplog.records)


def test_unhandled_exception_in_static_mount_returns_json(client, caplog):
    with patch.object(StaticFiles, "get_response", side_effect=OSError(SECRET)):
        response = client.get("/static/does-not-matter.css")

    assert_json_500(response, caplog.records)


def test_unhandled_exception_in_404_handler_returns_json(client, caplog):
    with patch("src.router.templates.TemplateResponse", side_effect=ValueError(SECRET)):
        response = client.get("/definitely-missing")

    assert_json_500(response, caplog.records)


def test_each_error_gets_a_distinct_id(client):
    with patch("src.router.templates.TemplateResponse", side_effect=RuntimeError()):
        first = client.get("/about").json()["error_id"]
        second = client.get("/about").json()["error_id"]

    assert first != second


def test_existing_error_responses_are_unchanged(client):
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
