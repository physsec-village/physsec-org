import os
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg import sql

from src.store import db, migrate
from src.store.config import migration_database_url


MIGRATION_TEST_DATABASE = "psv_migrate_test"
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:psv_test_password@127.0.0.1:55432/psv_test",
)


def _migration_files():
    return sorted(migrate.migrations_dir().glob("*.sql"))


def _admin_conninfo(database: str) -> str:
    # The migrator only accepts URLs, so swap the database path in place.
    return urlsplit(TEST_DATABASE_URL)._replace(path=f"/{database}").geturl()


@pytest.fixture
def migration_test_database():
    assert MIGRATION_TEST_DATABASE.endswith("_test")
    maintenance_url = _admin_conninfo("postgres")

    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(MIGRATION_TEST_DATABASE)
            )
        )
        conn.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(MIGRATION_TEST_DATABASE)
            )
        )

    try:
        yield _admin_conninfo(MIGRATION_TEST_DATABASE)
    finally:
        db.close_pool()
        with psycopg.connect(maintenance_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(MIGRATION_TEST_DATABASE)
                )
            )


def test_migrator_applies_pending_migrations_once(
    monkeypatch, migration_test_database
):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_test_database)
    migration_files = _migration_files()

    assert migrate.apply_migrations() == len(migration_files)
    assert migrate.apply_migrations() == 0

    with psycopg.connect(migration_test_database) as conn:
        metadata_version = conn.execute(
            "SELECT version FROM store.schema_metadata WHERE singleton"
        ).fetchone()[0]
        migration_count = conn.execute(
            "SELECT COUNT(*) FROM public.schema_migrations"
        ).fetchone()[0]

    assert metadata_version == db.SCHEMA_VERSION
    assert migration_count == len(migration_files)


def test_production_migration_database_requires_tls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://example.test/store")

    with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL"):
        migration_database_url()

    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql://example.test/store?sslmode=require",
    )
    assert migration_database_url().endswith("sslmode=require")


def test_migrator_adopts_schema_created_without_tracking(
    monkeypatch, migration_test_database
):
    # Databases set up with `psql -f` (or by Supabase) have no tracking table.
    # They are adopted at the baseline, and only later migrations run.
    migration_files = _migration_files()
    initial = migration_files[0]
    assert initial.name.startswith(migrate.BASELINE_VERSION)
    with psycopg.connect(migration_test_database) as conn:
        conn.execute(initial.read_text())
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_test_database)

    assert migrate.apply_migrations() == len(migration_files) - 1

    with psycopg.connect(migration_test_database) as conn:
        versions = conn.execute(
            "SELECT version FROM public.schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(migrate._version(f.name),) for f in migration_files]


def test_migrator_skips_without_migration_url(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "")

    assert migrate.main() == 0
