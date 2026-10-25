# Physical Security Village Website

This repository contains the FastAPI-based website for Physical Security Village (PSV). It serves server-rendered Jinja templates, static assets, a contact form backed by SMTP, and a set of content pages for talks, games, archives, resources, and volunteer intake.

## Stack

- Python 3.14
- FastAPI
- Jinja2 templates
- Static CSS and image assets
- `fastapi-mail` for the contact form
- Docker Compose for local/prod container runs
- Optional `systemd` unit for host-managed deployment

## Application Layout

- `src/main.py`: FastAPI app setup, static mount, router registration
- `src/router.py`: main page routes
- `src/forms/router.py`: volunteer page, calls page, contact email endpoint
- `src/forms/email.py`: SMTP configuration from environment variables
- `src/store/`: store catalog, PostgreSQL persistence, Stripe checkout, and
  the `/store/admin` UI (`admin.py`, `admin_auth.py`)
- `templates/`: page templates, navbar, footer, base layout, 404 page
- `static/`: global and page-specific CSS, logos, SVG assets
- `Dockerfile`: container image definition
- `docker-compose.yml`: blue/green app deployment, with per-checkout Compose
  interpolation so production and dev share a host
- `psv-website.service`: the production `systemd` unit the deployment role installs
- `deploy/`: deploy script, nginx virtual hosts, and the [deploy runbook](deploy/README.md)

## Routes

The app currently serves these user-facing routes:

- `/`
- `/about`
- `/involved`
- `/content`
- `/contact`
- `/talks`
- `/games`
- `/materials`
- `/archives`
- `/forms/volunteer`
- `/forms/calls`
- `/forms/email` (`POST`)
- `/store`
- `/store/collection/{slug}`
- `/store/product/{slug}`
- `/store/search?q=`
- `/store/catalog` (301 redirect to `/store`)
- `/store/checkout`
- `/store/confirmed`
- `/store/webhook` (`POST`, Stripe-signed)
- `/store/admin` (see [Store admin](#store-admin))

## Local Development

Install dependencies and run the app:

```bash
uv sync
uv run fastapi dev src/main.py
```

If you are not using `uv`, install from `pyproject.toml` with your preferred Python environment manager and run FastAPI directly.

The containerized path is:

```bash
docker compose --profile blue up --build
```

The compose file defines identical `blue` and `green` services for blue/green
deployment; run one colour locally. Blue publishes on `127.0.0.1:8080` (green
on `127.0.0.1:8082`).

## Environment Variables

The contact form depends on SMTP settings supplied through `.env` and loaded by Docker Compose. Based on the code, these values are required:

- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_FROM`
- `RECEIVER_EMAIL`

These optional values override the Gmail SMTP defaults:

- `MAIL_SERVER` (default: `smtp.gmail.com`)
- `MAIL_PORT` (default: `587`)
- `MAIL_STARTTLS` (default: `true`)
- `MAIL_SSL_TLS` (default: `false`)
- `MAIL_VALIDATE_CERTS` (default: `true`)

Turnstile uses `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`, and an optional
comma-separated `TURNSTILE_ALLOWED_HOSTNAMES` allowlist (default:
`physsec.org,www.physsec.org`).

`APP_ENV` defaults to `development`. Docker Compose sets it to `production`,
which makes both Turnstile keys mandatory and causes startup to fail if bot
protection is missing or only partially configured.
The deployment workflow also restricts `.env` to the deployment account with
mode `0600` before restarting the service.

The compose file restricts Uvicorn's trusted proxy headers to Docker bridge
networks. The reverse proxy must replace any client-supplied `X-Forwarded-For`
header rather than append to it; per-IP rate limiting depends on this boundary.

### Store configuration

The store is disabled by default. While `STORE_ENABLED=false`, store routes are
hidden, `/readyz` does not depend on PostgreSQL, and no store database or Stripe
configuration is required. Set `STORE_ENABLED=true` only after applying the
migration and configuring the deployment environment; enabled store
misconfiguration fails application startup.

The store uses a private PostgreSQL VM managed in the
`physsec-village/physsec-oci` repository. Production URLs must require TLS
(`sslmode=require`, `verify-ca`, or `verify-full`). Use the environment's
restricted application role in `DATABASE_URL` (`store_app` in production,
`store_dev_app` on dev), and keep the owner role URL in
`MIGRATION_DATABASE_URL` for migrations only. Both secrets belong only in the
deployment `.env`; they must not be committed or sent to the browser.

Schema changes are versioned in `db/migrations` and applied by:

```sh
MIGRATION_DATABASE_URL=postgresql://postgres:psv_test_password@127.0.0.1:55432/psv_test uv run python -m src.store.migrate
```

Deploys run pending migrations automatically when `MIGRATION_DATABASE_URL` is
non-empty in `.env`; leaving it empty skips migrations. The database roles,
TLS configuration, and backups are owned by the `physsec-oci`
`ansible/roles/postgres` role. Backups run on the database VM.

The store tables live in the `store` schema, which `PUBLIC` cannot use; only
the application role is granted access. Migrations grant the role named by
`DATABASE_URL` (or `store_app` when it is unset), so each environment's role
gets the same privileges without a per-environment migration.

The catalog lives in PostgreSQL: products, their variants and images, and
ordered collections and groups are explicit data. A product can appear in
several groups or collections. Only published products and collections appear
in the store. Products, variants, stock and collection membership are edited in
the [store admin](#store-admin); collections, groups and images are still
managed with SQL. There is no startup import.

The seed migration inserts the initial catalog with every variant's stock at 0.
Nothing is purchasable until inventory is counted and stock is set in the admin.

Prices and available inventory are resolved server-side in integer cents. Carts
contain `variant_id`/quantity pairs. SKUs are optional, opaque inventory identifiers;
they do not determine product grouping, pricing, or URLs. Image URLs in
`store.product_images.url` are used directly; seeded images live under
`/static/images/store/`.

- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` enable Stripe Checkout.
- `STORE_PUBLIC_ORIGIN` is the canonical HTTPS origin used for Stripe redirects.
- `STORE_SHIP_COUNTRIES` is a comma-separated country allowlist.
- `STRIPE_SHIPPING_RATE_IDS` optionally supplies Stripe shipping rates.
- `STORE_AUTOMATIC_TAX=true` enables Stripe Tax.
- `STORE_RESERVATION_MINUTES` controls reservation lifetime from 31 minutes to
  24 hours (default `35`, leaving a buffer above Stripe's 30-minute minimum).

Checkout creation atomically reserves inventory before contacting Stripe.
Provider calls use the durable checkout ID as their idempotency key. Signed
webhooks consume or release reservations and record an event ledger in the same
transaction as order state. Payment, fulfillment, manual review, and refund
states remain independent. `/readyz` verifies PostgreSQL connectivity and the
expected store schema version;
`/healthz` remains the process liveness probe.

Store integration tests run against disposable PostgreSQL rather than a mock or
SQLite compatibility layer:

```sh
docker compose -f docker-compose.test.yml up -d
MIGRATION_DATABASE_URL=postgresql://postgres:psv_test_password@127.0.0.1:55432/psv_test uv run python -m src.store.migrate
uv run pytest
```

Set `TEST_DATABASE_URL` to override the local test URL. Never point tests at the
production database.

#### Store admin

`/store/admin` is a small server-rendered admin UI for the store: it lists
every product with its stock, reservations and availability; edits a product's
name, URL slug, description, features, collections and published/featured
flags, and each variant's label, SKU, UPC, price, stock and published flag;
creates products and adds variants; and lists orders, shows their items and
shipping address, and updates fulfillment and review state. Products and
variants cannot be deleted (the application role's only `DELETE` grant is on
collection membership); unpublish them instead. An unpublished variant is
hidden from the store and cannot be bought, but stays on past orders, and a
published product must keep at least one published variant. Refunds are issued in the Stripe
dashboard and recorded from Stripe's webhook.

The admin UI returns 404 while the store is disabled. Sign-in is a
**temporary placeholder with hardcoded `admin`/`admin` credentials** in
`src/store/admin_auth.py`, for exploring the store on the dev deployment; it
must be replaced with a real login before this reaches `main`. Sessions are
signed with a per-process secret, so every restart or deploy signs you out.
Every form carries a CSRF token, the session cookie is `HttpOnly` and
`SameSite=Strict`, and admin responses are sent with `Cache-Control: no-store`.
Stock edits are rejected if stock changed since the form loaded or if the new
value is below the units reserved by open checkouts.

#### Migrating off Supabase

1. Provision roles and the `psv_store` database with the `physsec-oci` playbook.
   Put both PostgreSQL URLs in the production `.env`, then deploy once to create
   the schema while the store remains disabled.
2. Do not copy data from Supabase. The store has never taken an order there,
   and its catalog tables predate the current schema. The deploy's migrations
   create the schema and seed the catalog on the new database.
3. Verify `/readyz` and row counts. Only then enable the store if desired.
4. Pause the Supabase project, keep it for a week, then delete it to stop
   billing.

## Deployment Notes

- The `Dockerfile` installs the exact dependency versions in `uv.lock` with a
  pinned uv release and pinned Python base-image digest, then starts the site
  with `fastapi run src/main.py --proxy-headers --port 8080`.
- Production (`https://physsec.org`, `/opt/psv-website`) and dev
  (`https://dev.physsec.org`, `/opt/psv-website-dev`) run on the OCI app host
  alongside Odoo. The host is provisioned by the `physsec-village/physsec-oci`
  `ansible/roles/website` role: the `psv-deploy` deployment account, both
  checkouts and their `.env` files, the systemd units, the nginx upstream
  includes and the `sudo` rule for reloading nginx. That host shares a private
  network with the store PostgreSQL VM; other hosts cannot reach the database.
- `psv-website.service` documents the production unit the role installs; the
  dev unit (`psv-website-dev`) differs only in its path.
- The app serves `/healthz` for liveness and `/readyz` for store database
  readiness. The compose file uses the liveness endpoint.
- Pushes to `main` deploy production; pushes to the branch in the `DEV_BRANCH`
  repository variable deploy dev, and manual dispatch can deploy any branch to
  dev. See [`deploy/README.md`](deploy/README.md) for how a deploy works and
  the GitHub setup.
- Deploys are zero-downtime blue/green: [`deploy/deploy.sh`](deploy/deploy.sh)
  builds and starts the idle colour while the active one keeps serving, applies
  pending store migrations when configured, and switches nginx only after the
  new container passes its health check. The systemd units' `ExecStart` and
  `ExecReload` use the same script for boot and manual service operations.
- The nginx virtual hosts and security-header policy are versioned under
  [`deploy/nginx`](deploy/nginx/README.md). Deploys do not install them; the
  `website` role copies them from the production checkout, so re-run the
  playbook after changing them.

## Placeholders To Replace

The repository still contains several stubbed or provisional values that should be replaced before considering the site complete.

### Metadata and configuration

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `pyproject.toml` | `description = "Add your description here"` | Real package/project description |
| `.env` inputs consumed by `src/forms/email.py` and `src/forms/router.py` | `MAIL_USERNAME`, `MAIL_PASSWORD`, `RECEIVER_EMAIL` are expected but not documented in-repo beyond code | Real SMTP credentials and destination inbox |
| `psv-website.service` | `WorkingDirectory=/opt/psv-website` | Actual deployment path if this unit is used |
| `.github/workflows/deploy.yml` | Repository variable `DEV_BRANCH` | Branch the dev environment should track |

### Disabled or "coming soon" site sections

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/get-involved.html` | `Sponsorship details coming soon` | Real sponsorship workflow, package, or contact path |

### Pages with intentionally incomplete content

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/archives.html` | Archive copy says materials are still being organized and only links onward to talks and games | Real archive content, event recaps, or per-conference pages |
| `templates/pages/materials.html` | Materials page says written reference material is still being expanded and only offers contact/Discord paths | Real documents, slide decks, references, downloads, or external resources |
| `templates/pages/calls.html` | Several opportunities are generic, rolling, seasonal, or "published when the next CFP window opens" rather than event-specific | Actual conference names, dates, deadlines, and submission/application links |

### Stub data

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/talks.html` | Hard-coded sample talk archive entries with generic speaker names and no recordings/external links | Real PSV talks, speakers, dates, and media links |

### Legacy external asset/link dependencies to review

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/games.html` | Game links point at legacy `physsec.org` game URLs; thumbnails are now locally managed | Confirmed maintained game URLs or locally managed routes |
| `templates/pages/games/hid.html` | Embedded image paths reference archived `/web/...` URLs | Local static assets or current maintained URLs |

## Current State Summary

The site already has a coherent frontend structure, working contact and
volunteer email paths, locally managed game thumbnails, and a Stripe-backed
store commerce foundation. Store inventory and production Stripe configuration
must be loaded before checkout is enabled. The main remaining areas are
organizational content, real event/archive data, store media management,
sponsorship decisions, legacy game routes, and deployment-specific operations.
