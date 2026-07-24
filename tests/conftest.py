import os
import tempfile

_test_store_dir = tempfile.TemporaryDirectory(prefix="psv-tests-")

# Application startup intentionally validates these settings. Tests use
# inert values so route tests do not depend on a developer's local .env file.
os.environ.update(
    {
        "APP_ENV": "test",
        "MAIL_USERNAME": "test@example.com",
        "MAIL_PASSWORD": "test-password",
        "RECEIVER_EMAIL": "receiver@example.com",
        "STORE_DB_PATH": f"{_test_store_dir.name}/store.db",
    }
)
