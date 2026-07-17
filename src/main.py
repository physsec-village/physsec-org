from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .forms.router import router as form_router
from .router import router as root_router
from .router import not_found
from .store import db
from .store.admin_router import router as store_admin_router
from .store.admin_router import warn_if_unprotected_admin
from .store.router import router as store_router
from .store.seed import seed_mock_data

exceptions = {
    404: not_found,
}

app = FastAPI(exception_handlers=exceptions)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=db.MEDIA_DIR), name="media")


@app.on_event("startup")
def startup():
    db.init_db()
    warn_if_unprotected_admin()
    seed_mock_data()

app.include_router(root_router)
app.include_router(form_router)
app.include_router(store_router)
app.include_router(store_admin_router)
