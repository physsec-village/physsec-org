import unittest
from unittest.mock import AsyncMock, patch

import httpx

from src.forms.turnstile import (
    TurnstileSettings,
    get_turnstile_settings,
    verify_turnstile_token,
)


class TurnstileSettingsTests(unittest.TestCase):
    def test_turnstile_can_be_disabled(self):
        settings = TurnstileSettings(
            turnstile_site_key="", turnstile_secret_key="", _env_file=None
        )
        self.assertEqual(settings.turnstile_site_key, "")

    def test_partial_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must both be set"):
            TurnstileSettings(
                turnstile_site_key="site", turnstile_secret_key="", _env_file=None
            )

    def test_enabled_turnstile_requires_allowed_hostname(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            TurnstileSettings(
                turnstile_site_key="site",
                turnstile_secret_key="secret",
                turnstile_allowed_hostnames="",
                _env_file=None,
            )


class TurnstileVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_turnstile_settings.cache_clear()

    def tearDown(self):
        get_turnstile_settings.cache_clear()

    @staticmethod
    def _client_with_response(payload):
        response = AsyncMock()
        response.raise_for_status = lambda: None
        response.json = lambda: payload
        client = AsyncMock()
        client.__aenter__.return_value.post.return_value = response
        return client

    async def test_disabled_turnstile_accepts_submission(self):
        settings = TurnstileSettings(
            turnstile_site_key="", turnstile_secret_key="", _env_file=None
        )
        with patch("src.forms.turnstile.get_turnstile_settings", return_value=settings):
            self.assertTrue(await verify_turnstile_token("", None))

    async def test_valid_contact_token_is_accepted(self):
        client = self._client_with_response(
            {"success": True, "action": "contact", "hostname": "physsec.org"}
        )
        with (
            patch.dict(
                "os.environ",
                {"TURNSTILE_SITE_KEY": "site", "TURNSTILE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("src.forms.turnstile.httpx.AsyncClient", return_value=client),
        ):
            self.assertTrue(await verify_turnstile_token("token", "192.0.2.1"))

        post = client.__aenter__.return_value.post
        self.assertEqual(
            post.await_args.args[0],
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        )
        self.assertEqual(
            post.await_args.kwargs["data"],
            {"secret": "secret", "response": "token", "remoteip": "192.0.2.1"},
        )

    async def test_missing_token_is_rejected_when_enabled(self):
        with patch.dict(
            "os.environ",
            {"TURNSTILE_SITE_KEY": "site", "TURNSTILE_SECRET_KEY": "secret"},
            clear=True,
        ):
            self.assertFalse(await verify_turnstile_token("", None))

    async def test_wrong_action_is_rejected(self):
        client = self._client_with_response(
            {"success": True, "action": "other", "hostname": "physsec.org"}
        )
        with (
            patch.dict(
                "os.environ",
                {"TURNSTILE_SITE_KEY": "site", "TURNSTILE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("src.forms.turnstile.httpx.AsyncClient", return_value=client),
        ):
            self.assertFalse(await verify_turnstile_token("token", None))

    async def test_unapproved_hostname_is_rejected(self):
        client = self._client_with_response(
            {"success": True, "action": "contact", "hostname": "attacker.example"}
        )
        with (
            patch.dict(
                "os.environ",
                {"TURNSTILE_SITE_KEY": "site", "TURNSTILE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("src.forms.turnstile.httpx.AsyncClient", return_value=client),
        ):
            self.assertFalse(await verify_turnstile_token("token", None))

    async def test_siteverify_network_error_fails_closed(self):
        client = AsyncMock()
        client.__aenter__.return_value.post.side_effect = httpx.ConnectError("offline")
        with (
            patch.dict(
                "os.environ",
                {"TURNSTILE_SITE_KEY": "site", "TURNSTILE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("src.forms.turnstile.httpx.AsyncClient", return_value=client),
        ):
            self.assertFalse(await verify_turnstile_token("token", None))


if __name__ == "__main__":
    unittest.main()
