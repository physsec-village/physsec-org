"""Clerk-shaped session tokens for admin tests, shared across test modules."""

import os
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Sessions are signed with a throwaway key and verified offline through
# CLERK_JWT_KEY, so no test talks to Clerk.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ["CLERK_JWT_KEY"] = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)
ORIGIN = os.environ["STORE_PUBLIC_ORIGIN"]
ADMIN_USER = "user_admin"


def session_token(user_id: str = ADMIN_USER, *, admin=True, **claims) -> str:
    """Return a Clerk-shaped session JWT with the customised metadata claim."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "sid": f"sess_{user_id}",
        "azp": ORIGIN,
        "iss": "https://clerk.example.test",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "metadata": {"admin": admin},
        **claims,
    }
    return jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256")
