import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from .forms.email import get_mail_config
from .forms.router import router as form_router
from .forms.turnstile import get_turnstile_settings
from .limiter import limiter
from .router import not_found
from .router import router as root_router
from .store import db
from .store.config import store_enabled, validate_store_config
from .store.router import router as store_router
from .store.seed import bootstrap_catalog


def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please try again later."},
    )


async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    # Starlette's ServerErrorMiddleware calls this for any exception that
    # escapes the routes, middleware, mounts, or other exception handlers.
    # It re-raises afterwards, so uvicorn still logs its own traceback; this
    # record adds the request context and the error_id the client receives.
    error_id = uuid.uuid4().hex
    # The path only: query strings can carry tokens such as Stripe session IDs.
    logger.exception(
        "unhandled_exception error_id=%s method=%s path=%r",
        error_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    # This response is built outside all user middleware, so it carries its
    # own no-store headers instead of relying on them.
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "error_id": error_id},
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

exceptions = {
    404: not_found,
    RateLimitExceeded: rate_limit_exceeded,
    Exception: unhandled_exception,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first submission, if required configuration is invalid
    get_mail_config()
    get_turnstile_settings()
    app.state.store_enabled = store_enabled()
    if not app.state.store_enabled:
        yield
        return

    validate_store_config()
    db.open_pool()
    try:
        db.require_schema()
        bootstrap_catalog()
        yield
    finally:
        db.close_pool()


app = FastAPI(exception_handlers=exceptions, lifespan=lifespan)
app.state.limiter = limiter
app.state.store_enabled = False

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=db.MEDIA_DIR, check_dir=False), name="media")

app.include_router(root_router)
app.include_router(form_router)
app.include_router(store_router)
