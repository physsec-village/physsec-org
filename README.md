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
- `RECEIVER_EMAIL`

Current mail behavior assumes Gmail SMTP:

- server: `smtp.gmail.com`
- port: `587`
- STARTTLS enabled

## Deployment Notes

- The `Dockerfile` starts the site with `fastapi run src/main.py --proxy-headers --port 8080`.
- `psv-website.service` expects the repository to live at `/opt/psv-website`.
- The service file is an example deployment artifact, not a portable installer; adjust paths and service management to match the target host.

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
| `templates/navbar.html` | Store nav item disabled with `PSV Store coming soon` / `Store coming soon` | Real store URL or remove the nav item |
| `templates/footer.html` | Store footer item disabled with `Store coming soon` | Real store URL or remove the footer item |
| `templates/pages/get-involved.html` | `Sponsorship details coming soon` | Real sponsorship workflow, package, or contact path |

### Pages with intentionally incomplete content

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/archives.html` | Archive copy says materials are still being organized and only links onward to talks and games | Real archive content, event recaps, or per-conference pages |
| `templates/pages/materials.html` | Materials page says written reference material is still being expanded and only offers contact/Discord paths | Real documents, slide decks, references, downloads, or external resources |
| `templates/pages/calls.html` | Several opportunities are generic, rolling, seasonal, or "published when the next CFP window opens" rather than event-specific | Actual conference names, dates, deadlines, and submission/application links |

### Stub data and mock interactions

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/talks.html` | Hard-coded sample talk archive entries with generic speaker names and no recordings/external links | Real PSV talks, speakers, dates, and media links |
| `templates/pages/volunteer-form.html` | Form submit handler only hides the form and shows a success message; no backend submission exists | Real submission flow, validation, storage, and notification handling |

### Legacy external asset/link dependencies to review

| File | Current placeholder | What should replace it |
| --- | --- | --- |
| `templates/pages/games.html` | Thumbnails and game links point at legacy `physsec.org` WordPress/game URLs | Confirmed maintained URLs or locally managed assets/routes |
| `templates/pages/games/hid.html` | Embedded image paths reference archived `/web/...` URLs | Local static assets or current maintained URLs |

## Current State Summary

The site already has a coherent frontend structure, a working FastAPI app shell, and a contact email path. The main unfinished areas are organizational content, real event/archive data, store/sponsorship decisions, volunteer form backend integration, and deployment-specific configuration.
