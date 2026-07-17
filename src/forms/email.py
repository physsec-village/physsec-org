from functools import lru_cache

from fastapi_mail import ConnectionConfig
from pydantic_settings import BaseSettings, SettingsConfigDict


class MailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mail_username: str
    mail_password: str
    receiver_email: str
    mail_server: str = "smtp.gmail.com"
    mail_port: int = 587
    mail_starttls: bool = True
    mail_validate_certs: bool = True


@lru_cache
def get_settings() -> MailSettings:
    return MailSettings()


@lru_cache
def get_mail_config() -> ConnectionConfig:
    settings = get_settings()
    return ConnectionConfig(
        MAIL_USERNAME=settings.mail_username,
        MAIL_PASSWORD=settings.mail_password,
        MAIL_FROM=settings.mail_username,
        MAIL_PORT=settings.mail_port,
        MAIL_SERVER=settings.mail_server,
        MAIL_FROM_NAME="PSV No Reply",
        MAIL_STARTTLS=settings.mail_starttls,
        MAIL_SSL_TLS=False,
        VALIDATE_CERTS=settings.mail_validate_certs,
    )
