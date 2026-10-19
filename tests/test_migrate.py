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


MIGRATION_TEST_APP_ROLE = "psv_migrate_test_app"


@pytest.fixture
def migration_test_app_role(migration_test_database):
    # Roles are cluster-wide, so drop this one again. Its privileges in the
    # test database have to go first, and that database still exists here.
    role = sql.Identifier(MIGRATION_TEST_APP_ROLE)
    with psycopg.connect(_admin_conninfo("postgres"), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(role))
        conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(role))
    try:
        yield MIGRATION_TEST_APP_ROLE
    finally:
        with psycopg.connect(migration_test_database, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(role))
        with psycopg.connect(_admin_conninfo("postgres"), autocommit=True) as conn:
            conn.execute(sql.SQL("DROP ROLE {}").format(role))


def _app_role_url(role: str) -> str:
    return f"postgresql://{role}@127.0.0.1:55432/{MIGRATION_TEST_DATABASE}"


def test_migrator_grants_the_database_url_role(
    monkeypatch, migration_test_database, migration_test_app_role
):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_test_database)
    monkeypatch.setenv("DATABASE_URL", _app_role_url(migration_test_app_role))

    assert migrate.apply_migrations() == len(_migration_files())

    with psycopg.connect(migration_test_database) as conn:
        privileges = conn.execute(
            """
            SELECT has_schema_privilege(%(role)s, 'store', 'USAGE'),
                   has_table_privilege(%(role)s, 'store.products', 'SELECT, INSERT, UPDATE'),
                   has_table_privilege(%(role)s, 'store.products', 'DELETE'),
                   has_table_privilege(%(role)s, 'store.schema_metadata', 'SELECT'),
                   has_table_privilege(%(role)s, 'store.schema_metadata', 'INSERT'),
                   has_table_privilege(%(role)s, 'store.schema_metadata', 'UPDATE')
            """,
            {"role": migration_test_app_role},
        ).fetchone()
        # Default privileges cover tables later migrations create.
        conn.execute("CREATE TABLE store.migrate_test_later (id int)")
        later = conn.execute(
            "SELECT has_table_privilege(%s, 'store.migrate_test_later', 'SELECT')",
            (migration_test_app_role,),
        ).fetchone()[0]

    assert privileges == (True, True, False, True, False, False)
    assert later


def test_migrator_defaults_to_store_app(monkeypatch, migration_test_database):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_test_database)
    monkeypatch.delenv("DATABASE_URL")

    assert migrate.app_role() == "store_app"
    assert migrate.apply_migrations() == len(_migration_files())


def test_migrator_rejects_a_missing_app_role(monkeypatch, migration_test_database):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", migration_test_database)
    monkeypatch.setenv("DATABASE_URL", _app_role_url("psv_migrate_test_missing"))

    with pytest.raises(psycopg.errors.RaiseException, match="does not exist"):
        migrate.apply_migrations()


def test_app_role_migration_requires_the_runner(migration_test_database):
    grant_migration = next(
        f for f in _migration_files() if f.name.endswith("_grant_app_role.sql")
    )
    with psycopg.connect(migration_test_database) as conn:
        conn.execute(_migration_files()[0].read_text())
        with pytest.raises(psycopg.errors.RaiseException, match="psv.app_role"):
            conn.execute(grant_migration.read_text())


def test_app_role_hides_an_invalid_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:s3cret@host/db?bogus")

    with pytest.raises(ValueError) as excinfo:
        migrate.app_role()
    assert "s3cret" not in str(excinfo.value)
