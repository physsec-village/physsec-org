from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import JSONResponse
from fastapi_mail import FastMail, MessageSchema, MessageType
from .email import conf
from .models import FormSchema
import os

from ..dependencies import templates

router = APIRouter(prefix="/forms")


@router.get("/volunteer", response_class=HTMLResponse)
def volunteer_form_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/volunteer-form.html")


@router.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/calls.html")

@router.post("/email")
async def simple_send(email: FormSchema) -> JSONResponse:
    html = f"""
    <html>
        <body>
            <h2>New Message from {email.name}</h2>
            <p><strong>Subject:</strong> {email.subject}</p>
            <p><strong>From:</strong> {email.email}</p>
            <p><strong>Message:</strong></p>
            <p>{email.message}</p>
            <hr>
            <p>This email was sent via FastAPI Mail.</p>
        </body>
    </html>
    """
    
    message = MessageSchema(
        subject=f"Physsec.org - Contact Us -  {email.subject} - {email.name}",
        recipients=[os.getenv("RECEIVER_EMAIL")],  # Receiver from environment
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)
    return JSONResponse(status_code=200, content={"message": "email has been sent"})
