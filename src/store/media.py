"""Product images uploaded through the admin.

Uploads are written under STORE_MEDIA_DIR, which the app serves at /media, and
referenced by URL from store.product_images like any other image. The file
type is read from the bytes, never from the client's filename or content type.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from . import db

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_URL_LENGTH = 2000
UPLOAD_PREFIX = "/media/store/"


class MediaError(ValueError):
    """A rejected image whose message is safe to show the admin."""


def image_extension(data: bytes) -> str | None:
    """Return the file extension for a supported image, from its signature."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "gif"
    return None


def _upload_dir() -> Path:
    return Path(db.MEDIA_DIR) / "store"


def save_image(data: bytes) -> str:
    """Store an uploaded image and return the URL it is served at."""
    if not data:
        raise MediaError("Choose an image file to upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError("Images must be 5 MB or smaller.")
    extension = image_extension(data)
    if extension is None:
        raise MediaError("Images must be WebP, PNG, JPEG or GIF files.")
    folder = _upload_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}.{extension}"
    (folder / name).write_bytes(data)
    return UPLOAD_PREFIX + name


def image_url(value: str) -> str:
    """Validate an image address typed into the admin (a site path or https)."""
    url = value.strip()
    if not url:
        raise MediaError("Upload an image file or enter an image address.")
    if len(url) > MAX_URL_LENGTH:
        raise MediaError("The image address is too long.")
    if not (url.startswith("/") and not url.startswith("//")) and not url.startswith(
        "https://"
    ):
        raise MediaError("Image addresses must start with / or https://.")
    return url


def remove_image(url: str) -> None:
    """Delete an uploaded file that no image row references any more.

    Images that live elsewhere (the static directory, other sites) are left
    alone; only files this module wrote are removed.
    """
    if not url.startswith(UPLOAD_PREFIX):
        return
    name = url.removeprefix(UPLOAD_PREFIX)
    if not name or name != Path(name).name:
        return
    try:
        (_upload_dir() / name).unlink()
    except FileNotFoundError:
        pass
