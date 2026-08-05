<div align="center">
  <img src="static/psv-compact-logo.svg" alt="Physical Security Village" width="160">

  # Physical Security Village

  The website and online store for [Physical Security Village](https://physsec.org).
</div>

## About

This repository powers the PSV website: event information, talks, games,
community resources, contact and volunteer forms, and an optional storefront.
It is a server-rendered FastAPI application with Jinja templates and a
PostgreSQL-backed Stripe checkout flow.

## Tech stack

- Python 3.14, FastAPI, and Jinja
- PostgreSQL hosted on Supabase
- Stripe Checkout
- Cloudflare Turnstile
- Docker Compose and nginx

## Run locally

Install [uv](https://docs.astral.sh/uv/), then:

```bash
cp .env.example .env
uv sync
uv run fastapi dev src/main.py
```

Add local mail settings to `.env` before starting the app. Turnstile may remain
unset in development. The site will be available at `http://127.0.0.1:8000`.

To run the production container locally instead:

```bash
docker compose up --build
```

Compose serves the app at `http://127.0.0.1:8080` and requires production
Turnstile settings in `.env`.

## Configuration

Start with [`.env.example`](.env.example). The main settings are:

| Area | Variables |
| --- | --- |
| Email | `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `RECEIVER_EMAIL` |
| Turnstile | `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_ALLOWED_HOSTNAMES` |
| Store | `STORE_ENABLED`, `DATABASE_URL`, `STORE_PUBLIC_ORIGIN` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_SHIPPING_RATE_IDS` |

The store is disabled by default. Before enabling it, apply the migration in
[`supabase/migrations`](supabase/migrations), configure PostgreSQL and Stripe,
and load inventory. New catalog items start with zero stock unless explicitly
configured otherwise.

## Tests

Tests use a disposable local PostgreSQL database:

```bash
docker compose -f docker-compose.test.yml up -d
PGPASSWORD=psv_test_password psql \
  postgresql://postgres@127.0.0.1:55432/psv_test \
  -f supabase/migrations/20260727000000_store_schema.sql
uv run pytest
```

`TEST_DATABASE_URL` can override the default loopback test database. The test
suite rejects remote database hosts.

## Project layout

```text
src/          FastAPI application, forms, and store logic
templates/    Jinja page templates
static/       Styles, scripts, images, and logos
supabase/     Database configuration and migrations
deploy/       Deployment and nginx configuration
tests/        Application and store tests
```

## Deployment

Merges to `main` deploy through GitHub Actions to a Docker Compose host. The
deployment script performs a health-checked container swap and rolls back on
failure. See [`deploy/nginx/README.md`](deploy/nginx/README.md) for reverse-proxy
setup and security-header notes.

Health endpoints are available at `/healthz` and `/readyz`.
