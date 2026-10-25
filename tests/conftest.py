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
                "TRUNCATE store.products, store.collections, store.checkouts, "
                "store.stripe_events "
                "RESTART IDENTITY CASCADE"
            )
    except psycopg.OperationalError:
        pytest.fail(
            "PostgreSQL tests require the test database; "
            "run `docker compose -f docker-compose.test.yml up -d`."
        )
    yield
    db.close_pool()


@pytest.fixture
def catalog_factory():
    from src.store import db

    class CatalogFactory:
        def product(
            self, slug="test-tool", name="Test Tool", *, description="Test product",
            features=(), featured=False, published=True, variants=None, images=(),
        ):
            with db.connection() as conn:
                product = dict(conn.execute(
                    "INSERT INTO products(slug,name,description,features,featured,published) "
                    "VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                    (slug, name, description, list(features), featured, published),
                ).fetchone())
                product["variants"] = []
                for position, variant in enumerate(variants or [{}]):
                    product["variants"].append(dict(conn.execute(
                        "INSERT INTO variants(product_id,name,sku,price_cents,stock_on_hand,"
                        "position,published) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (product["id"], variant.get("name", ""), variant.get("sku"),
                         variant.get("price_cents", 2500), variant.get("stock", 3),
                         variant.get("position", position),
                         variant.get("published", True)),
                    ).fetchone()))
                for position, url in enumerate(images):
                    conn.execute(
                        "INSERT INTO product_images(product_id,url,alt,position) VALUES(%s,%s,%s,%s)",
                        (product["id"], url, name, position),
                    )
            return product

        def collection(self, slug="tools", title="Tools", *, published=True,
                       position=0, description="", tag="", blurb=""):
            with db.connection() as conn:
                return dict(conn.execute(
                    "INSERT INTO collections(slug,title,published,position,description,tag,blurb) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (slug, title, published, position, description, tag, blurb),
                ).fetchone())

        def group(self, collection, title="", *, position=0, tag="", lede=""):
            with db.connection() as conn:
                return dict(conn.execute(
                    "INSERT INTO collection_groups(collection_id,title,position,tag,lede) "
                    "VALUES(%s,%s,%s,%s,%s) RETURNING *",
                    (collection["id"], title, position, tag, lede),
                ).fetchone())

        def add(self, group, product, *, position=0):
            with db.connection() as conn:
                conn.execute(
                    "INSERT INTO collection_items(group_id,product_id,position) VALUES(%s,%s,%s)",
                    (group["id"], product["id"], position),
                )

    return CatalogFactory()
