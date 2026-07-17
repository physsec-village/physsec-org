import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from .forms.email import get_mail_config
from .forms.router import router as form_router
from .limiter import limiter
from .router import router as root_router
from .router import not_found


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
    # Fail at startup, not on first submission, if mail env vars are missing
    get_mail_config()
    yield


app = FastAPI(exception_handlers=exceptions, lifespan=lifespan)
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(root_router)
app.include_router(form_router)
