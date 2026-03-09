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
