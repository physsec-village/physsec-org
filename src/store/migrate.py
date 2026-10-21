"""Apply store database migrations."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from .config import migration_database_url

LOGGER = logging.getLogger("store.migrate")
MIGRATION_LOCK_KEY = 80260727000000
# Databases set up before this runner existed (Supabase, or `psql -f` on a
# local test database) already contain this migration but have no record of it.
BASELINE_VERSION = "20260727000000"
# Used when DATABASE_URL names no role, matching the first migration.
DEFAULT_APP_ROLE = "store_app"


def migrations_dir() -> Path:
    """Return the repository-level migration directory."""
    return Path(__file__).resolve().parents[2] / "db" / "migrations"


def app_role() -> str:
    """Return the role the application connects as, from DATABASE_URL.

    Each environment has its own application role (production `store_app`,
    dev `store_dev_app`), so migrations grant whichever role this
    environment's DATABASE_URL names rather than a fixed one.
    """
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        return DEFAULT_APP_ROLE
    try:
        parameters = conninfo_to_dict(value)
    except psycopg.ProgrammingError:
        # The parser's message can quote the URL, password included.
        raise ValueError(
            "DATABASE_URL is not a valid PostgreSQL connection string."
        ) from None
    return parameters.get("user") or DEFAULT_APP_ROLE


def _version(filename: str) -> str:
    return filename.split("_", 1)[0]


def _ensure_schema_migrations(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
    untracked = conn.execute(
        "SELECT to_regclass('public.schema_migrations') IS NULL"
        " AND to_regclass('store.schema_metadata') IS NOT NULL"
    ).fetchone()[0]
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version text primary key,
            filename text not null,
            applied_at timestamptz not null default now()
        )
        """
    )
    if untracked:
        conn.execute(
            "INSERT INTO public.schema_migrations (version, filename) VALUES (%s, %s)",
            (BASELINE_VERSION, "baseline"),
        )
        LOGGER.info("recorded existing schema as %s", BASELINE_VERSION)


def apply_migrations() -> int:
    """Apply pending store migrations and return the number applied."""
    migration_files = sorted(migrations_dir().glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migration files found in {migrations_dir()}")

    role = app_role()
    LOGGER.info("application role: %s", role)

    applied = 0
    with psycopg.connect(migration_database_url(), autocommit=False) as conn:
        for migration_file in migration_files:
            version = _version(migration_file.name)
            sql = migration_file.read_text(encoding="utf-8")
            with conn.transaction():
                _ensure_schema_migrations(conn)
                recorded = conn.execute(
                    "SELECT 1 FROM public.schema_migrations WHERE version = %s",
                    (version,),
                ).fetchone()
                if recorded:
                    continue
                # Migrations read the role with current_setting('psv.app_role').
                conn.execute("SELECT set_config('psv.app_role', %s, true)", (role,))
                conn.execute(sql)
                conn.execute(
                    """
                    INSERT INTO public.schema_migrations (version, filename)
                    VALUES (%s, %s)
                    """,
                    (version, migration_file.name),
                )
                applied += 1
                LOGGER.info("applied %s", migration_file.name)

    if applied == 0:
        LOGGER.info("up to date")
    return applied


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Deploys always invoke the runner; the value Compose actually parsed from
    # .env decides whether this environment manages its schema.
    if not os.getenv("MIGRATION_DATABASE_URL", "").strip():
        LOGGER.info("MIGRATION_DATABASE_URL is not set; skipping store migrations")
        return 0
    try:
        apply_migrations()
    except Exception as exc:
        print(f"Store migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
