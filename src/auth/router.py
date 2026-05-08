from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..dependencies import templates

router = APIRouter(prefix="/auth")


@router.get("/login/oauth/authoize", response_class=HTMLResponse)
async def oauth_authorize(request: Request):
    return templates.TemplateResponse(request=request, name="pages/login.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/login.html")


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/register.html")


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/forgot_password.html")

