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
  the `/store/admin` UI (`admin.py`, Clerk sign-in in `admin_auth.py`)
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
in the store. The whole catalog is edited in the [store admin](#store-admin):
products, variants, stock, images, collections, their groups and the order of
everything. There is no startup import.

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
states remain independent. Payments themselves are managed in the Stripe
dashboard; the store only listens. The webhook endpoint (`/store/webhook`)
should be subscribed to `checkout.session.completed`,
`checkout.session.async_payment_succeeded`, `checkout.session.expired`,
`charge.refunded` and `charge.dispute.created`: paid sessions become orders,
expired ones release stock, refunds update the order's refund state, and a
dispute flags the order for review. Other event types are recorded and
ignored. `/readyz` verifies PostgreSQL connectivity and the
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

`/store/admin` is a server-rendered admin UI for the store. It edits the whole
catalog:

- **Products**: a searchable, filterable list with stock, reservations and
  availability; a product's name, URL slug, description, features, collections
  and published/featured flags; each variant's label, SKU, UPC, price, stock and
  published flag, plus adding, reordering and deleting variants; and product
  images, uploaded (WebP, PNG, JPEG or GIF, up to 5 MB, stored under
  `STORE_MEDIA_DIR` and served from `/media`) or referenced by address, with
  alt text, ordering and removal.
- **Review**: before go-live, every product carries a *reviewed* mark,
  separate from *published*. The Review page walks through the unreviewed
  products one at a time with the full editor, so each can be corrected and
  marked reviewed (or skipped and revisited); the product list shows the mark
  and can filter on it, and a product page can clear it.
- **Collections**: creating, editing, reordering, publishing and deleting
  collections; the headed groups inside each one; and which products appear in
  each group, in what order.
- **Orders**: a list filterable by fulfillment and review state, each order's
  items, totals and shipping address, fulfillment and review updates, and a link
  to the payment in the Stripe dashboard.
- **Stripe**: which Stripe settings are configured (never the secrets), the
  webhook endpoint and the events it needs, and the ledger of received webhook
  deliveries with their outcome, for checking that payments reach the store.

Checkouts and orders reference the variants they sold, so a variant that has
ever been reserved or sold, and the product that owns it, cannot be deleted;
unpublish them instead. An unpublished variant is hidden from the store and
cannot be bought, but stays on past orders, and a published product must keep
at least one published variant. Everything else in the catalog can be deleted.
Refunds and disputes are handled in the Stripe dashboard and recorded from
Stripe's webhooks.

The admin UI returns 404 while the store is disabled. Sign-in uses
[Clerk](https://clerk.com): `/store/admin/login` mounts Clerk's sign-in
component, and every other admin request verifies the Clerk session cookie
(`__session`) server-side with `clerk-backend-api`, including that its `azp`
claim is `STORE_PUBLIC_ORIGIN`. A signed-in user is only an admin when their
Clerk **public metadata** contains `{"admin": true}`; set this on the user in
the Clerk dashboard (Users, then Metadata). Everyone else gets a 403 page with
a sign-out button. The flag is read from the session token itself, so each
Clerk instance must include public metadata in its session token (Sessions,
then "Customize session token"):

```json
{ "metadata": "{{user.public_metadata}}" }
```

Without that claim every user is treated as a non-admin. Removing the flag
locks the user out when their token is next refreshed, within a minute.

Dev (`dev.physsec.org`) uses a Clerk development instance and production uses
the production instance; both are configured with `CLERK_PUBLISHABLE_KEY` and
`CLERK_SECRET_KEY`. The optional `CLERK_JWT_KEY` (the instance's PEM public
key) verifies sessions without fetching Clerk's signing keys. For local
development set `STORE_PUBLIC_ORIGIN` to the origin you browse from, such as
`http://localhost:8000`; Clerk development instances accept `+clerk_test`
email addresses with the fixed verification code `424242`, so no mailbox is
needed. Sign-up is governed by the Clerk instance's settings and does not grant
admin access.

Every form carries a CSRF token bound to the Clerk session, and admin
responses are sent with `Cache-Control: no-store`. Stock edits are rejected if
stock changed since the form loaded or if the new value is below the units
reserved by open checkouts, and a product or collection form loaded before
another edit is rejected rather than undoing that edit. The nginx virtual
hosts raise the request body limit to 6 MB only for the image upload route
(`/store/admin/products/<id>/images`); every other route stays at 64 KB.

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
