import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.responses import HTMLResponse, JSONResponse, Response

from .dependencies import templates
from .forms.email import get_mail_config
from .forms.router import router as form_router
from .forms.turnstile import get_turnstile_settings
from .limiter import limiter
from .router import not_found
from .router import router as root_router
from .store import db
from .store.admin import NotAnAdmin, not_an_admin
from .store.admin import public_router as store_admin_public_router
from .store.admin import router as store_admin_router
from .store.config import store_enabled, store_published, validate_store_config
from .store.router import router as store_router
from .store.router import webhook_router as store_webhook_router


def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please try again later."},
    )


# Served when the 500 template itself cannot be rendered.
FALLBACK_ERROR_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>Something Went Wrong</title></head>
<body>
<h1>Something went wrong</h1>
<p>Please try again in a moment. Reference: {error_id}</p>
</body>
</html>
"""


def accept_qualities(header: str) -> dict[str, float]:
    """Map each media range in an Accept header to its quality value.

    Media types are lowercased. A missing q defaults to 1.0, values are clamped
    to [0, 1], and an unparseable q counts as 0 so the range is ignored.
    """
    qualities = {}
    for media_range in header.lower().split(","):
        media_type, *params = (part.strip() for part in media_range.split(";"))
        quality = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip() == "q":
                try:
                    quality = min(max(float(value), 0.0), 1.0)
                except ValueError:
                    quality = 0.0
        if media_type:
            qualities[media_type] = quality
    return qualities


def wants_html(request: Request) -> bool:
    """Return whether the client prefers an HTML error page over JSON.

    Browser navigations name text/html explicitly; fetch() calls, Stripe
    webhooks, and other API clients do not, so they get the JSON body. HTML
    must also be acceptable (q > 0) and strictly preferred over JSON, whose
    quality comes from the most specific of application/json, application/*,
    and */*.
    """
    qualities = accept_qualities(request.headers.get("accept", ""))
    html = qualities.get("text/html", 0.0)
    json = next(
        (
            qualities[media_type]
            for media_type in ("application/json", "application/*", "*/*")
            if media_type in qualities
        ),
        0.0,
    )
    return html > 0 and html > json


def error_page(request: Request, error_id: str) -> Response:
    """Render the HTML 500 page showing error_id as the reference.

    If the template itself fails, log that and return a minimal static page so
    the browser still gets the reference instead of a second unhandled error.
    """
    try:
        return templates.TemplateResponse(
            request=request,
            name="500.html",
            context={"error_id": error_id, "error_page": True},
            status_code=500,
        )
    except Exception:
        logger.exception("error_page_render_failed error_id=%s", error_id)
        return HTMLResponse(
            FALLBACK_ERROR_PAGE.format(error_id=error_id), status_code=500
        )


async def unhandled_exception(request: Request, exc: Exception) -> Response:
    """Log an unhandled exception and return a 500 that reveals no internals.

    Starlette's ServerErrorMiddleware calls this for any exception that
    escapes the routes, middleware, mounts, or other exception handlers.
    It re-raises afterwards, so uvicorn still logs its own traceback; this
    record adds the request context and the error_id the client receives.
    Browsers get the HTML error page and every other client gets JSON.

    This handler is async on purpose: a sync handler runs in a threadpool
    where the active exception is no longer set, so exc is passed explicitly.
    """
    error_id = uuid.uuid4().hex
    # The path only: query strings can carry tokens such as Stripe session IDs.
    logger.exception(
        "unhandled_exception error_id=%s method=%s path=%r",
        error_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    if wants_html(request):
        response = error_page(request, error_id)
    else:
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "error_id": error_id},
        )
    # This response is built outside all user middleware, so it carries its
    # own no-store headers instead of relying on them.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Vary"] = "Accept"
    return response


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

exceptions = {
    404: not_found,
    RateLimitExceeded: rate_limit_exceeded,
    NotAnAdmin: not_an_admin,
    Exception: unhandled_exception,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first submission, if required configuration is invalid
    get_mail_config()
    get_turnstile_settings()
    app.state.store_enabled = store_enabled()
    # Published means publicly reachable, so it implies enabled.
    app.state.store_published = app.state.store_enabled and store_published()
    if not app.state.store_enabled:
        yield
        return

    validate_store_config()
    db.open_pool()
    try:
        db.require_schema()
        yield
    finally:
        db.close_pool()


app = FastAPI(exception_handlers=exceptions, lifespan=lifespan)
app.state.limiter = limiter
app.state.store_enabled = False
app.state.store_published = False


@app.middleware("http")
async def private_store_admin(request: Request, call_next):
    response = await call_next(request)
    # Includes redirects and 404s, so no admin response is ever cached. An
    # unpublished storefront is admin-only too, so it gets the same treatment.
    path = request.url.path
    if path.startswith("/store/admin") or (
        path.startswith("/store") and not request.app.state.store_published
    ):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=db.MEDIA_DIR, check_dir=False), name="media")

app.include_router(root_router)
app.include_router(form_router)
app.include_router(store_router)
app.include_router(store_webhook_router)
app.include_router(store_admin_public_router)
app.include_router(store_admin_router)
