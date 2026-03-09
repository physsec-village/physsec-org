from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .dependencies import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/landing.html")


@router.get("/about", response_class=HTMLResponse)
def about_us_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/about-us.html")


@router.get("/involved", response_class=HTMLResponse)
def get_involved_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/get-involved.html")


@router.get("/content", response_class=HTMLResponse)
def content_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/content.html")


@router.get("/contact", response_class=HTMLResponse)
def contact_us_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/contact-us.html")


@router.get("/talks", response_class=HTMLResponse)
def talks_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/talks.html")


@router.get("/games", response_class=HTMLResponse)
def games_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/games.html")


@router.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/materials.html")
