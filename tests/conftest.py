import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:psv_test_password@127.0.0.1:55432/psv_test",
)


def _validate_test_database_url() -> None:
    parameters = conninfo_to_dict(TEST_DATABASE_URL)
    host = parameters.get("host", "")
    database = parameters.get("dbname", "")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "TEST_DATABASE_URL must use a loopback PostgreSQL host; "
            "remote databases are never valid test targets."
        )
    if not database.lower().endswith(("_test", "-test", "test")):
        raise RuntimeError("TEST_DATABASE_URL must name an unmistakable test database.")


_validate_test_database_url()

# Application startup intentionally validates these settings. Tests use
# inert values so route tests do not depend on a developer's local .env file.
os.environ.update(
    {
        "APP_ENV": "test",
        "MAIL_USERNAME": "test@example.com",
        "MAIL_PASSWORD": "test-password",
        "RECEIVER_EMAIL": "receiver@example.com",
        "STORE_ENABLED": "true",
        "DATABASE_URL": TEST_DATABASE_URL,
    }
)


@pytest.fixture(autouse=True)
def reset_store_database():
    """Give every test an empty migrated PostgreSQL store schema."""
    from src.store import db

    db.close_pool()
    try:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(
                "TRUNCATE store.categories, store.checkouts, store.stripe_events "
                "RESTART IDENTITY CASCADE"
            )
    except psycopg.OperationalError:
        pytest.fail(
            "PostgreSQL tests require the test database; "
            "run `docker compose -f docker-compose.test.yml up -d`."
        )
    yield
    db.close_pool()
