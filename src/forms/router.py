import html
import logging
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import JSONResponse
from fastapi_mail import FastMail, MessageSchema, MessageType

from .email import get_mail_config, get_settings
from .models import FormSchema, VolunteerFormSchema
from .turnstile import get_turnstile_settings, verify_turnstile_token

from ..dependencies import templates
from ..limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forms")


@router.get("/volunteer", response_class=HTMLResponse)
def volunteer_form_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/volunteer-form.html",
        context={"turnstile_site_key": get_turnstile_settings().turnstile_site_key},
    )


@router.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    return templates.TemplateResponse(request=request, name="pages/calls.html")


async def send_contact_email(message: MessageSchema) -> None:
    """Send a contact email, raising when SMTP delivery fails."""
    await FastMail(get_mail_config()).send_message(message)


def display_value(value: str) -> str:
    return html.escape(value) if value else "Not provided"


@router.post("/email")
@limiter.limit("5/hour")
async def simple_send(
    request: Request, email: FormSchema
) -> JSONResponse:
    submission_id = uuid4().hex
    if email.website:
        # Honeypot field was filled in; pretend success so bots can't tell
        logger.warning("Honeypot triggered for submission %s", submission_id)
        return JSONResponse(status_code=200, content={"message": "email has been sent"})

    client_ip = request.client.host if request.client else None
    if not await verify_turnstile_token(email.turnstile_token, client_ip):
        return JSONResponse(
            status_code=403,
            content={"detail": "CAPTCHA verification failed. Please try again."},
        )

    logger.info("Processing contact submission %s", submission_id)

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

    try:
        await send_contact_email(message)
    except Exception:
        # SMTP errors can contain message data, and a timeout may occur after
        # delivery. Log neither the exception nor advice that could duplicate it.
        logger.error("Email delivery outcome unknown for submission %s", submission_id)
        return JSONResponse(
            status_code=500,
            content={"detail": "We couldn't confirm whether the message was delivered."},
        )

    logger.info("Email delivered for submission %s", submission_id)
    return JSONResponse(status_code=200, content={"message": "email has been sent"})


@router.post("/volunteer")
@limiter.limit("5/hour")
async def submit_volunteer_application(
    request: Request, application: VolunteerFormSchema
) -> JSONResponse:
    submission_id = uuid4().hex
    if application.website:
        logger.warning("Volunteer honeypot triggered for submission %s", submission_id)
        return JSONResponse(
            status_code=200, content={"message": "application has been received"}
        )

    client_ip = request.client.host if request.client else None
    if not await verify_turnstile_token(
        application.turnstile_token, client_ip, expected_action="volunteer"
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "CAPTCHA verification failed. Please try again."},
        )

    conferences = "".join(
        f"<li>{html.escape(conference)}</li>"
        for conference in application.conferences
    )
    body = f"""
    <html>
        <body>
            <h2>New PSV Volunteer Application</h2>
            <p><strong>Name:</strong> {html.escape(application.name)}</p>
            <p><strong>Email:</strong> {html.escape(str(application.email))}</p>
            <p><strong>Discord handle:</strong> {html.escape(application.discord_handle)}</p>
            <p><strong>Discord user ID:</strong> {html.escape(application.discord_user_id)}</p>
            <p><strong>Shirt size:</strong> {display_value(application.shirt_size)}</p>
            <p><strong>Location:</strong> {display_value(application.location)}</p>
            <p><strong>Food limitations:</strong> {html.escape(application.food_limitations)}</p>
            <p><strong>Interested conferences:</strong></p><ul>{conferences}</ul>
            <p><strong>Volunteered before:</strong> {html.escape(application.volunteered_before)}</p>
            <p><strong>Why they are interested:</strong></p>
            <p>{html.escape(application.interest).replace("\n", "<br>")}</p>
            <p><strong>Other information:</strong></p>
            <p>{display_value(application.other_information).replace("\n", "<br>")}</p>
            <p><strong>Storage/contact consent:</strong> Yes</p>
        </body>
    </html>
    """
    message = MessageSchema(
        subject="Physsec.org - New Volunteer Application",
        recipients=[get_settings().receiver_email],
        body=body,
        subtype=MessageType.html,
        reply_to=[application.email],
    )

    logger.info("Processing volunteer submission %s", submission_id)
    try:
        await send_contact_email(message)
    except Exception:
        logger.error(
            "Volunteer email delivery outcome unknown for submission %s",
            submission_id,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "We couldn't confirm whether the application was delivered."},
        )

    logger.info("Volunteer application delivered for submission %s", submission_id)
    return JSONResponse(
        status_code=200, content={"message": "application has been received"}
    )
