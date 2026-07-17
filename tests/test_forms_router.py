import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from src.forms.models import FormSchema
from src.forms.router import simple_send


def contact_form() -> FormSchema:
    return FormSchema(
        name="Private Name",
        email="private@example.com",
        subject="Private Subject",
        message="Private message body",
        turnstile_token="token",
    )


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/forms/email",
            "headers": [],
            "client": ("192.0.2.1", 1234),
        }
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


if __name__ == "__main__":
    unittest.main()
