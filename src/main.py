from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .forms.router import router as form_router
from .router import router as root_router

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(root_router)
app.include_router(form_router)
