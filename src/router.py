from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from .dependencies import templates
from .forms.turnstile import get_turnstile_settings
from .menu import FOOTNOTES, MENU
from .store import db

router = APIRouter()

SITEMAP_PATHS = (
    "/",
    "/about",
    "/involved",
    "/content",
    "/contact",
    "/materials",
    "/forms/calls",
    "/forms/volunteer",
)
STORE_SITEMAP_PATHS = ("/store", "/store/catalog")


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
    return templates.TemplateResponse(
        request=request,
        name="pages/contact-us.html",
        context={"turnstile_site_key": get_turnstile_settings().turnstile_site_key},
    )


@router.get("/talks", response_class=HTMLResponse)
def talks_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/talks.html")


@router.get("/games", response_class=HTMLResponse)
def games_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/games.html")


@router.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/materials.html")


@router.get("/menu", response_class=HTMLResponse)
def store_menu_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/store-menu.html",
        context={"menu": MENU, "menu_footnotes": FOOTNOTES},
    )


@router.get("/archives", response_class=HTMLResponse)
def archives_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/archives.html")


@router.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request):
    if not request.app.state.store_enabled:
        return Response(content="ready", media_type="text/plain")
    try:
        status = db.readiness()
    except OSError, RuntimeError:
        status = {}
    ready = isinstance(status, dict) and bool(status.get("ready"))
    return Response(
        content="ready" if ready else "not ready",
        status_code=200 if ready else 503,
        media_type="text/plain",
    )


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt():
    return "User-agent: *\nAllow: /\nSitemap: https://physsec.org/sitemap.xml\n"


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(request: Request):
    paths = SITEMAP_PATHS
    if request.app.state.store_enabled:
        paths += STORE_SITEMAP_PATHS
    urls = "".join(f"<url><loc>https://physsec.org{path}</loc></url>" for path in paths)
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        media_type="application/xml",
    )


async def not_found(request, exc):
    return templates.TemplateResponse(request=request, name="404.html", status_code=404)
