import unittest

from src.forms.email import MailSettings


class MailSettingsTests(unittest.TestCase):
    def test_sender_defaults_to_empty_for_username_fallback(self):
        settings = MailSettings(
            mail_username="sender@example.com",
            mail_password="secret",
            receiver_email="contact@example.com",
            _env_file=None,
        )
        self.assertEqual(settings.mail_from, "")
        self.assertFalse(settings.mail_ssl_tls)

    def test_sender_and_ssl_are_configurable(self):
        settings = MailSettings(
            mail_username="smtp-user",
            mail_password="secret",
            mail_from="sender@example.com",
            receiver_email="contact@example.com",
            mail_starttls=False,
            mail_ssl_tls=True,
            _env_file=None,
        )
        self.assertEqual(settings.mail_from, "sender@example.com")
        self.assertTrue(settings.mail_ssl_tls)


if __name__ == "__main__":
    unittest.main()
