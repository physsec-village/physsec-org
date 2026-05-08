from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .forms.router import router as form_router
from .router import router as root_router
from .odoo.router import router as odoo_router
from .auth.router import router as auth_router
from .router import not_found

exceptions = {
    404: not_found,
}

app = FastAPI(exception_handlers=exceptions)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(root_router)
app.include_router(auth_router)
app.include_router(form_router)
app.include_router(odoo_router)
