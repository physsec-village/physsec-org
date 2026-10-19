"""Credentials for the store admin UI.

The admin UI uses HTTP Basic authentication over the site's HTTPS origin. The
password is stored only as a scrypt hash in STORE_ADMIN_PASSWORD_HASH, encoded
without `$` so Docker Compose does not interpolate it from `.env`. Generate a
hash with:

    uv run python -m src.store.admin_auth
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import secrets
import sys
from dataclasses import dataclass

SCHEME = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
_MAX_N = 2**20


@dataclass(frozen=True)
class AdminCredentials:
    username: str
    password_hash: str

    def verify(self, username: str, password: str) -> bool:
        # Always run the hash so a wrong username costs the same as a wrong
        # password.
        password_ok = verify_password(password, self.password_hash)
        username_ok = hmac.compare_digest(
            username.encode("utf-8"), self.username.encode("utf-8")
        )
        return username_ok and password_ok

    def csrf_token(self) -> str:
        """Return a form token an attacker without the hash cannot derive."""
        return hmac.new(
            self.password_hash.encode("utf-8"),
            f"store-admin-csrf:{self.username}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=128 * r * (n + p + 2),
        dklen=32,
    )


def hash_password(password: str) -> str:
    """Return a self-describing scrypt hash for STORE_ADMIN_PASSWORD_HASH."""
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return ":".join(
        (
            SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64encode(salt),
            _b64encode(digest),
        )
    )


def _parse(encoded: str) -> tuple[int, int, int, bytes, bytes]:
    parts = encoded.split(":")
    if len(parts) != 6 or parts[0] != SCHEME:
        raise ValueError("STORE_ADMIN_PASSWORD_HASH is not a scrypt hash.")
    try:
        n, r, p = (int(part) for part in parts[1:4])
        salt, digest = _b64decode(parts[4]), _b64decode(parts[5])
    except ValueError as exc:
        raise ValueError("STORE_ADMIN_PASSWORD_HASH is malformed.") from exc
    if (
        n < 2**14
        or n > _MAX_N
        or n & (n - 1)
        or not 1 <= r <= 32
        or not 1 <= p <= 16
        or len(salt) < 16
        or len(digest) != 32
    ):
        raise ValueError("STORE_ADMIN_PASSWORD_HASH has unsafe parameters.")
    return n, r, p, salt, digest


def verify_password(password: str, encoded: str) -> bool:
    n, r, p, salt, digest = _parse(encoded)
    return hmac.compare_digest(_scrypt(password, salt, n, r, p), digest)


def admin_credentials() -> AdminCredentials | None:
    """Return configured admin credentials, or None when the UI is disabled."""
    username = os.getenv("STORE_ADMIN_USERNAME", "").strip()
    password_hash = os.getenv("STORE_ADMIN_PASSWORD_HASH", "").strip()
    if not username and not password_hash:
        return None
    if not username or not password_hash:
        raise ValueError(
            "STORE_ADMIN_USERNAME and STORE_ADMIN_PASSWORD_HASH must be set together."
        )
    if ":" in username:
        raise ValueError("STORE_ADMIN_USERNAME must not contain ':'.")
    _parse(password_hash)
    return AdminCredentials(username=username, password_hash=password_hash)


def main() -> int:
    password = getpass.getpass("Admin password: ")
    if len(password) < 12:
        print("Use at least 12 characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
