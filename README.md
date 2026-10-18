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
- `templates/`: page templates, navbar, footer, base layout, 404 page
- `static/`: global and page-specific CSS, logos, SVG assets
- `Dockerfile`: container image definition
- `docker-compose.yml`: single-service app deployment
- `psv-website.service`: example `systemd` unit for running Docker Compose on a host

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
- `/store/catalog`
- `/store/product/{product_id}`
- `/store/checkout`
- `/store/confirmed`
- `/store/webhook` (`POST`, Stripe-signed)

## Local Development

Install dependencies and run the app:

```bash
uv sync
uv run fastapi dev src/main.py
```

If you are not using `uv`, install from `pyproject.toml` with your preferred Python environment manager and run FastAPI directly.

The containerized path is:

```bash
docker compose up --build
```

The compose file publishes the app on `127.0.0.1:8080`.

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
(`sslmode=require`, `verify-ca`, or `verify-full`). Use the restricted
`store_app` role in `DATABASE_URL`, and keep the owner role URL in
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
`store_app` is granted access. A fresh
database imports the bundled catalog with zero stock, so checkout remains
unavailable until inventory is explicitly loaded. Prices and inventory are
always resolved server-side in integer cents and browser carts contain only
SKU/quantity pairs.

- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` enable Stripe Checkout.
- `STORE_PUBLIC_ORIGIN` is the canonical HTTPS origin used for Stripe redirects.
- `STORE_SHIP_COUNTRIES` is a comma-separated country allowlist.
- `STRIPE_SHIPPING_RATE_IDS` optionally supplies Stripe shipping rates.
- `STORE_AUTOMATIC_TAX=true` enables Stripe Tax.
- `STORE_RESERVATION_MINUTES` controls reservation lifetime from 31 minutes to
  24 hours (default `35`, leaving a buffer above Stripe's 30-minute minimum).
- `STORE_BOOTSTRAP_STOCK` controls initial stock during first-time import and
  defaults to `0` so new deployments fail closed.

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

#### Migrating off Supabase

1. Provision roles and the `psv_store` database with the `physsec-oci` playbook.
   Put both PostgreSQL URLs in the production `.env`, then deploy once to create
   the schema while the store remains disabled.
2. Copy data, unless Supabase holds nothing worth keeping (the store has never
   been enabled in production, so a fresh catalog may be all you need). Use a
   `postgres:17` client container on the app host. Supabase's direct host is
   IPv6-only, so use the session-pooler URL from its Connect dialog. Put the old
   Supabase owner URL and new `MIGRATION_DATABASE_URL` in a temporary `0600`
   env file and pass it with `--env-file`, not command-line arguments. Pipe
   `pg_dump --data-only --schema=store --exclude-table=store.schema_metadata --no-owner --no-privileges`
   from the Supabase URL into
   `psql -v ON_ERROR_STOP=1 --single-transaction` on `MIGRATION_DATABASE_URL`.
   Identity sequence values are included in a data-only dump via `setval`.
3. Verify `/readyz` and row counts. Only then enable the store if desired.
4. Pause the Supabase project, keep it for a week, then delete it to stop
   billing.

## Deployment Notes

- The `Dockerfile` installs the exact dependency versions in `uv.lock` with a
  pinned uv release and pinned Python base-image digest, then starts the site
  with `fastapi run src/main.py --proxy-headers --port 8080`.
- `psv-website.service` expects the repository to live at `/opt/psv-website`.
- The service file is an example deployment artifact, not a portable installer; adjust paths and service management to match the target host.
- The app serves `/healthz` for liveness and `/readyz` for store database
  readiness. The compose file uses the liveness endpoint.
- Deploys invoke [`deploy/deploy.sh`](deploy/deploy.sh) directly as the
  deployment account, avoiding interactive `sudo` in GitHub Actions. The
  script builds the new image while the old container keeps serving, applies
  pending store migrations when configured, swaps containers only after the new
  one passes its health check, and otherwise rolls back to the previously
  tagged image (`psv-website:previous`) and fails the deploy. The systemd unit's
  `ExecStart` and `ExecReload` use the same script for boot and manual service
  operations; changes to the unit itself require an administrator to run
  `systemctl daemon-reload` on the host.
- A production nginx reverse-proxy configuration and security-header policy are
  versioned under [`deploy/nginx`](deploy/nginx/README.md). Install them on the
  host only after adapting certificate and distribution-specific paths, then
  validate with `nginx -t` before reloading nginx.

## Placeholders To Replace

The repository still contains several stubbed or provisional values that should be replaced before considering the site complete.

### Metadata and configuration

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `pyproject.toml` | `description = "Add your description here"` | Real package/project description |
| `.env` inputs consumed by `src/forms/email.py` and `src/forms/router.py` | `MAIL_USERNAME`, `MAIL_PASSWORD`, `RECEIVER_EMAIL` are expected but not documented in-repo beyond code | Real SMTP credentials and destination inbox |
| `psv-website.service` | `WorkingDirectory=/opt/psv-website` | Actual deployment path if this unit is used |

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
organizational content, real event/archive data, store administration,
sponsorship decisions, legacy game routes, and deployment-specific operations.
