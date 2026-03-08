from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="landing.html")


@app.get("/about", response_class=HTMLResponse)
def about_us_page(request: Request):
    return templates.TemplateResponse(request=request, name="about-us.html")


@app.get("/involved", response_class=HTMLResponse)
def get_involved_page(request: Request):
    return templates.TemplateResponse(request=request, name="get-involved.html")


@app.get("/content", response_class=HTMLResponse)
def content_page(request: Request):
    return templates.TemplateResponse(request=request, name="content.html")


@app.get("/volunteer", response_class=HTMLResponse)
def volunteer_form_page(request: Request):
    return templates.TemplateResponse(request=request, name="about-us.html")
