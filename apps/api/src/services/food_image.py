"""Food-photo validation, EXIF stripping, and at-rest storage.

Boundary hardening for an untrusted image upload:
  * size is capped (mirrors the sidecar's 5 MB image limit);
  * the format is validated from the *decoded bytes* (Pillow), not the declared
    content-type or filename, and only jpeg/png/webp are accepted;
  * a decompression-bomb guard bounds pixel count;
  * the image is re-encoded so EXIF / GPS / other metadata is dropped;
  * the stored path is server-generated (UUID filename under a per-user dir) --
    no caller-supplied string ever enters the path, so there is no traversal
    surface.

The file lives on the private uploads volume (owner-scoped, never web-served),
mirroring the user_documents storage pattern.
"""

import os
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Bound decoded pixel count to defang decompression bombs (a small compressed
# file can decode to billions of pixels). 50 MP comfortably covers any phone
# camera. We enforce this ourselves from the header dimensions before decoding,
# because Pillow's MAX_IMAGE_PIXELS only *raises* above 2x the limit (between 1x
# and 2x it merely warns); MAX_IMAGE_PIXELS is kept as a backstop.
_MAX_IMAGE_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS

# Pillow format name -> stored extension. The media type sent to the vision
# provider is derived from the same validated format, never the client's claim.
_ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


class FoodImageError(Exception):
    """Base class for food-image validation/storage failures."""


class InvalidImageError(FoodImageError):
    """The upload is empty, truncated, or not a decodable image."""


class UnsupportedImageError(FoodImageError):
    """The image decoded but is not an accepted format (jpeg/png/webp)."""


class ImageTooLargeError(FoodImageError):
    """The upload exceeds the configured size cap."""


class ProcessedImage:
    """A validated, metadata-stripped image ready to store and send."""

    __slots__ = ("data", "extension", "media_type")

    def __init__(self, data: bytes, extension: str, media_type: str) -> None:
        self.data = data
        self.extension = extension
        self.media_type = media_type


def process_upload(raw: bytes) -> ProcessedImage:
    """Validate, size-check, and re-encode an uploaded image (strips metadata).

    Raises ``ImageTooLargeError`` / ``InvalidImageError`` / ``UnsupportedImageError``.
    """
    if not raw:
        raise InvalidImageError("empty upload")
    if len(raw) > settings.food_image_max_bytes:
        raise ImageTooLargeError(f"image exceeds {settings.food_image_max_bytes} bytes")

    # First pass: integrity check (verify() detects truncated/corrupt files but
    # consumes the image object, so we reopen for the actual decode).
    try:
        with Image.open(BytesIO(raw)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError("could not decode image") from exc
    except Image.DecompressionBombError as exc:
        raise InvalidImageError("image too large to decode") from exc

    try:
        with Image.open(BytesIO(raw)) as img:
            fmt = (img.format or "").upper()
            if fmt not in _ALLOWED_FORMATS:
                raise UnsupportedImageError(
                    "unsupported image format (allowed: jpeg, png, webp)"
                )
            extension, media_type = _ALLOWED_FORMATS[fmt]

            # Reject oversized images from the header dimensions BEFORE decoding,
            # so a decompression bomb never gets loaded into memory.
            width, height = img.size
            if width * height > _MAX_IMAGE_PIXELS:
                raise InvalidImageError("image dimensions exceed the supported limit")

            # Honor any EXIF orientation visually, then drop all metadata by
            # re-encoding from pixel data only (no exif=/icc_profile=/pnginfo=).
            oriented = ImageOps.exif_transpose(img)
            clean = BytesIO()
            if fmt == "JPEG":
                oriented.convert("RGB").save(clean, format="JPEG", quality=90)
            else:
                oriented.save(clean, format=fmt)
    except Image.DecompressionBombError as exc:
        raise InvalidImageError("image too large to decode") from exc
    except (UnsupportedImageError, InvalidImageError):
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError("could not process image") from exc

    return ProcessedImage(
        data=clean.getvalue(), extension=extension, media_type=media_type
    )


def _user_dir(user_id: uuid.UUID) -> Path:
    return Path(settings.upload_dir) / "food" / str(user_id)


def store_image(user_id: uuid.UUID, image: ProcessedImage) -> tuple[str, int]:
    """Write a processed image to the private uploads volume.

    Returns ``(storage_path, size_bytes)``. The filename is a server-generated
    UUID; nothing caller-supplied enters the path.
    """
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = f"{uuid.uuid4().hex}.{image.extension}"
    path = directory / filename
    # Create the file with 0600 atomically (O_EXCL on a UUID name) so there is
    # no window where the photo is world-readable before a chmod.
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(image.data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path), len(image.data)


def delete_stored_image(storage_path: str) -> None:
    """Best-effort unlink of a stored image, confined to the uploads volume.

    Validates containment before unlinking so a malformed/poisoned stored path
    can never delete a file outside the uploads root. Never raises.
    """
    try:
        base = Path(settings.upload_dir).resolve()
        target = Path(storage_path).resolve()
        # Must be strictly *inside* the uploads root -- never the root itself.
        if base not in target.parents:
            logger.warning("Refusing to delete path outside uploads root")
            return
        target.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to delete stored food image", error=str(exc))
