from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..dependencies import templates


router = APIRouter(prefix="/forms")


@router.get("/volunteer", response_class=HTMLResponse)
def volunteer_form_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/volunteer-form.html")
