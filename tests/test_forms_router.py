import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from starlette.requests import Request

from src.forms.models import FormSchema, VolunteerFormSchema
from src.forms.router import simple_send, submit_volunteer_application


def contact_form() -> FormSchema:
    return FormSchema(
        name="Private Name",
        email="private@example.com",
        subject="Private Subject",
        message="Private message body",
        turnstile_token="token",
    )


def request(path: str = "/forms/email") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("192.0.2.1", 1234),
        }
    )


def volunteer_form() -> VolunteerFormSchema:
    return VolunteerFormSchema(
        name="Volunteer Name",
        email="volunteer@example.com",
        discord_handle="volunteer",
        discord_user_id="123456789012345678",
        food_limitations="None",
        conferences=["DEF CON"],
        volunteered_before="no",
        interest="I want to help <script>alert(1)</script>",
        consent=True,
        turnstile_token="token",
    )


class ContactDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_is_returned_after_delivery(self):
        deliver = AsyncMock()
        with (
            patch(
                "src.forms.router.verify_turnstile_token",
                new=AsyncMock(return_value=True),
            ),
            patch("src.forms.router.send_contact_email", new=deliver),
            patch(
                "src.forms.router.get_settings",
                return_value=SimpleNamespace(receiver_email="contact@example.com"),
            ),
        ):
            response = await simple_send(request=request(), email=contact_form())

        self.assertEqual(response.status_code, 200)
        deliver.assert_awaited_once()

    async def test_delivery_failure_returns_error_without_logging_pii(self):
        deliver = AsyncMock(
            side_effect=RuntimeError("SMTP rejected private@example.com")
        )
        with (
            patch(
                "src.forms.router.verify_turnstile_token",
                new=AsyncMock(return_value=True),
            ),
            patch("src.forms.router.send_contact_email", new=deliver),
            patch(
                "src.forms.router.get_settings",
                return_value=SimpleNamespace(receiver_email="contact@example.com"),
            ),
            self.assertLogs("src.forms.router", level="INFO") as logs,
        ):
            response = await simple_send(request=request(), email=contact_form())

        self.assertEqual(response.status_code, 500)
        combined_logs = "\n".join(logs.output)
        self.assertNotIn("Private Name", combined_logs)
        self.assertNotIn("private@example.com", combined_logs)
        self.assertNotIn("Private Subject", combined_logs)
        self.assertNotIn("Private message body", combined_logs)


class VolunteerDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_is_emailed_after_volunteer_captcha(self):
        deliver = AsyncMock()
        captcha = AsyncMock(return_value=True)
        with (
            patch("src.forms.router.verify_turnstile_token", new=captcha),
            patch("src.forms.router.send_contact_email", new=deliver),
            patch(
                "src.forms.router.get_settings",
                return_value=SimpleNamespace(receiver_email="contact@example.com"),
            ),
        ):
            response = await submit_volunteer_application(
                request=request("/forms/volunteer"), application=volunteer_form()
            )

        self.assertEqual(response.status_code, 200)
        captcha.assert_awaited_once_with(
            "token", "192.0.2.1", expected_action="volunteer"
        )
        message = deliver.await_args.args[0]
        self.assertIn("&lt;script&gt;", message.body)
        self.assertNotIn("<script>alert", message.body)
        self.assertEqual(str(message.reply_to[0].email), "volunteer@example.com")

    async def test_application_delivery_failure_does_not_log_pii(self):
        deliver = AsyncMock(side_effect=RuntimeError("volunteer@example.com"))
        with (
            patch(
                "src.forms.router.verify_turnstile_token",
                new=AsyncMock(return_value=True),
            ),
            patch("src.forms.router.send_contact_email", new=deliver),
            patch(
                "src.forms.router.get_settings",
                return_value=SimpleNamespace(receiver_email="contact@example.com"),
            ),
            self.assertLogs("src.forms.router", level="INFO") as logs,
        ):
            response = await submit_volunteer_application(
                request=request("/forms/volunteer"), application=volunteer_form()
            )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("volunteer@example.com", "\n".join(logs.output))

    async def test_volunteer_honeypot_does_not_send(self):
        application = volunteer_form().model_copy(update={"website": "spam"})
        with (
            patch("src.forms.router.verify_turnstile_token", new=AsyncMock()) as captcha,
            patch("src.forms.router.send_contact_email", new=AsyncMock()) as deliver,
        ):
            response = await submit_volunteer_application(
                request=request("/forms/volunteer"), application=application
            )

        self.assertEqual(response.status_code, 200)
        captcha.assert_not_awaited()
        deliver.assert_not_awaited()

    async def test_captcha_failure_does_not_send_application(self):
        with (
            patch(
                "src.forms.router.verify_turnstile_token",
                new=AsyncMock(return_value=False),
            ),
            patch("src.forms.router.send_contact_email", new=AsyncMock()) as deliver,
        ):
            response = await submit_volunteer_application(
                request=request("/forms/volunteer"), application=volunteer_form()
            )

        self.assertEqual(response.status_code, 403)
        deliver.assert_not_awaited()


class VolunteerValidationTests(unittest.TestCase):
    def test_rejects_unknown_or_duplicate_choices(self):
        with self.assertRaises(ValidationError):
            VolunteerFormSchema(
                **volunteer_form().model_dump(exclude={"conferences"}),
                conferences=["Unknown"],
            )
        with self.assertRaises(ValidationError):
            VolunteerFormSchema(
                **volunteer_form().model_dump(exclude={"conferences"}),
                conferences=["DEF CON", "DEF CON"],
            )
        with self.assertRaises(ValidationError):
            VolunteerFormSchema(
                **volunteer_form().model_dump(exclude={"shirt_size"}),
                shirt_size="5XL",
            )

    def test_rejects_false_consent_and_invalid_discord_id(self):
        with self.assertRaises(ValidationError):
            VolunteerFormSchema(
                **volunteer_form().model_dump(exclude={"consent"}), consent=False
            )
        with self.assertRaises(ValidationError):
            VolunteerFormSchema(
                **volunteer_form().model_dump(exclude={"discord_user_id"}),
                discord_user_id="not-an-id",
            )


if __name__ == "__main__":
    unittest.main()
