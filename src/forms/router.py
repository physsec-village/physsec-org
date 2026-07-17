import html
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from starlette.responses import JSONResponse
from fastapi_mail import FastMail, MessageSchema, MessageType

from .email import get_mail_config, get_settings
from .models import FormSchema

from ..dependencies import templates
from ..limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forms")


@router.get("/volunteer", response_class=HTMLResponse)
def volunteer_form_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/volunteer-form.html")


@router.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/calls.html")


async def send_contact_email(message: MessageSchema, form: FormSchema) -> None:
    try:
        await FastMail(get_mail_config()).send_message(message)
    except Exception:
        # Log the full submission so a mail outage doesn't lose it
        logger.exception(
            "Failed to send contact email from %s <%s> (subject: %r); message text:\n%s",
            form.name,
            form.email,
            form.subject,
            form.message,
        )
    else:
        logger.info(
            "Sent contact email from %s <%s> (subject: %r)",
            form.name,
            form.email,
            form.subject,
        )


@router.post("/email")
@limiter.limit("5/hour")
async def simple_send(
    request: Request, email: FormSchema, background_tasks: BackgroundTasks
) -> JSONResponse:
    if email.website:
        # Honeypot field was filled in; pretend success so bots can't tell
        logger.warning("Honeypot triggered by %s <%s>", email.name, email.email)
        return JSONResponse(status_code=200, content={"message": "email has been sent"})

    logger.info(
        "Contact form submission from %s <%s> (subject: %r)",
        email.name,
        email.email,
        email.subject,
    )

    body = f"""
    <html>
        <body>
            <h2>New Message from {html.escape(email.name)}</h2>
            <p><strong>Subject:</strong> {html.escape(email.subject)}</p>
            <p><strong>From:</strong> {html.escape(email.email)}</p>
            <p><strong>Message:</strong></p>
            <p>{html.escape(email.message).replace("\n", "<br>")}</p>
            <hr>
            <p>This email was sent via FastAPI Mail.</p>
        </body>
    </html>
    """

    message = MessageSchema(
        subject=f"Physsec.org - Contact Us -  {email.subject} - {email.name}",
        recipients=[get_settings().receiver_email],
        body=body,
        subtype=MessageType.html,
        reply_to=[email.email],
    )

    background_tasks.add_task(send_contact_email, message, email)
    return JSONResponse(status_code=200, content={"message": "email has been sent"})
