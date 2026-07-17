import logging
from functools import lru_cache

import httpx
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Both empty (the default) disables Turnstile entirely
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    turnstile_allowed_hostnames: str = "physsec.org,www.physsec.org"

    @property
    def allowed_hostnames(self) -> frozenset[str]:
        return frozenset(
            hostname.strip().lower()
            for hostname in self.turnstile_allowed_hostnames.split(",")
            if hostname.strip()
        )

    @model_validator(mode="after")
    def require_both_keys(self) -> "TurnstileSettings":
        if bool(self.turnstile_site_key) != bool(self.turnstile_secret_key):
            raise ValueError(
                "TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY must both be set"
            )
        if self.turnstile_secret_key and not self.allowed_hostnames:
            raise ValueError("TURNSTILE_ALLOWED_HOSTNAMES must not be empty")
        return self


@lru_cache
def get_turnstile_settings() -> TurnstileSettings:
    return TurnstileSettings()


async def verify_turnstile_token(token: str, remote_ip: str | None) -> bool:
    """Verify a contact-form token with Cloudflare when Turnstile is enabled."""
    settings = get_turnstile_settings()
    if not settings.turnstile_secret_key:
        return True
    if not token:
        logger.warning("Submission without Turnstile token rejected")
        return False

    data = {"secret": settings.turnstile_secret_key, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(VERIFY_URL, data=data)
            response.raise_for_status()
            outcome = response.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("Turnstile siteverify unavailable or returned invalid JSON")
        return False

    if not isinstance(outcome, dict):
        logger.warning("Turnstile siteverify returned an unexpected response")
        return False
    if not outcome.get("success"):
        logger.warning("Turnstile rejected token: %s", outcome.get("error-codes"))
        return False
    if outcome.get("action") != "contact":
        logger.warning("Turnstile returned unexpected action: %r", outcome.get("action"))
        return False
    hostname = outcome.get("hostname")
    if not isinstance(hostname, str) or hostname.lower() not in settings.allowed_hostnames:
        logger.warning("Turnstile returned an unapproved hostname")
        return False
    return True
