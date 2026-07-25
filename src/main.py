import logging
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
from .store.config import validate_store_config
from .store.router import router as store_router
from .store.seed import bootstrap_catalog


def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please try again later."},
    )


logging.basicConfig(level=logging.INFO)

exceptions = {
    404: not_found,
    RateLimitExceeded: rate_limit_exceeded,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first submission, if required configuration is invalid
    get_mail_config()
    get_turnstile_settings()
    validate_store_config()
    db.init_db()
    bootstrap_catalog()
    yield


app = FastAPI(exception_handlers=exceptions, lifespan=lifespan)
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=db.MEDIA_DIR, check_dir=False), name="media")

app.include_router(root_router)
app.include_router(form_router)
app.include_router(store_router)
