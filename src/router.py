from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from .dependencies import templates
from .forms.turnstile import get_turnstile_settings

router = APIRouter()

SITEMAP_PATHS = (
    "/",
    "/about",
    "/involved",
    "/content",
    "/contact",
    "/games",
    "/materials",
    "/store",
    "/store/catalog",
    "/forms/calls",
    "/forms/volunteer",
)


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


@router.get("/archives", response_class=HTMLResponse)
def archives_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/archives.html")


@router.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt():
    return "User-agent: *\nAllow: /\nSitemap: https://physsec.org/sitemap.xml\n"


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    urls = "".join(
        f"<url><loc>https://physsec.org{path}</loc></url>" for path in SITEMAP_PATHS
    )
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        media_type="application/xml",
    )

async def not_found(request, exc):
    return templates.TemplateResponse(
        request=request, name="404.html", status_code=404
    )
