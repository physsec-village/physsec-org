# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Physical Security Village (PSV) website — a FastAPI web app with contact forms and a Stripe-powered store selling physical security tools and merchandise.

## Commands

```bash
# Install dependencies
uv sync

# Run development server
fastapi run src/main.py

# Build and run with Docker
docker compose up --build

# Run with Docker (detached)
docker compose up -d --force-recreate --build
```

There is no test or lint command currently configured.

## Environment Variables

Copy `.env.example` to `.env` before running locally:

- `MAIL_USERNAME` / `MAIL_PASSWORD` — Gmail SMTP credentials for contact forms
- `RECEIVER_EMAIL` — destination address for form submissions
- `STRIPE_SECRET_KEY` — Stripe API key; if missing, checkout stubs locally without error

## Architecture

```
src/
  main.py          # FastAPI app: mounts routers, static files, exception handlers
  router.py        # Root routes: /, /about, /talks, /games, /materials, /archives
  dependencies.py  # Shared Jinja2Templates instance
  forms/           # Contact form: routes, Pydantic model, fastapi-mail SMTP send
  store/           # E-commerce: routes, hardcoded product catalog, Stripe checkout

templates/         # Jinja2 templates; base.html + navbar/footer partials + pages/
static/            # CSS (styles.css, nav.css, footer.css), store.js, SVG/PNG assets
```

**Request flow:** FastAPI router → renders Jinja2 template via shared `templates` dependency → returns HTML. The store's cart state lives entirely in browser `localStorage` (managed by `static/store.js`); the backend only receives a cart payload at checkout time to create a Stripe session.

**Key design choices:**
- Products are hardcoded in `src/store/products.py` — no database.
- Stripe checkout is created server-side in `src/store/stripe.py`; on success, Stripe redirects to `/store/success`.
- Email is sent via Gmail SMTP using `fastapi-mail`; the `FormSchema` Pydantic model validates contact form input.
- Templates inherit from `templates/base.html`; page-specific CSS lives in `static/pages/`.

## Deployment

Merging to `main` triggers `.github/workflows/deploy.yml`, which SSHes into the VPS and runs `docker compose up -d --force-recreate --build`. The container serves on `127.0.0.1:8080` (assumed behind a reverse proxy). A systemd unit (`psv-website.service`) ensures the container starts on boot.
