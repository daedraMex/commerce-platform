"""Store public product images and build their public URLs."""

import hashlib
import warnings
from dataclasses import dataclass, replace
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.catalog.models import Media

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
FORMAT_TO_EXTENSION = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}
FORMAT_ERROR = "Only JPEG, PNG or WebP images are accepted."
SIZE_ERROR = "Images must be 10 MB or smaller."


class MediaRuleError(ValueError):
    """An uploaded file cannot become product media."""


@dataclass(frozen=True)
class PreparedMedia:
    """Everything read from one uploaded image, before it is stored."""

    content: bytes
    content_hash: str
    storage_key: str
    mime_type: str
    width: int
    height: int
    metadata: dict


def get_media_storage():
    """The configured media storage, reflecting the current settings."""
    config = settings.STORAGES.get("default", {})
    backend = config.get("BACKEND", "")
    options = dict(config.get("OPTIONS", {}))
    if backend == "django.core.files.storage.FileSystemStorage":
        options.setdefault("location", settings.MEDIA_ROOT)
        options.setdefault("base_url", settings.MEDIA_URL)
        return FileSystemStorage(**options)
    return storages["default"]


def media_url(storage_key):
    """The public URL for a storage key, built from MEDIA_BASE_URL."""
    base = (getattr(settings, "MEDIA_BASE_URL", "") or "").rstrip("/")
    key = storage_key.lstrip("/")
    return f"{base}/{key}" if base else f"/{key}"


def encode_image(image, image_format):
    """Re-encode an image with no EXIF, XMP, ICC or text metadata."""
    buffer = BytesIO()
    if image_format == "JPEG":
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=90, optimize=True, comment=b"", exif=b"")
    elif image_format == "PNG":
        image.save(buffer, format="PNG", optimize=True, icc_profile=None, exif=b"")
    else:
        image.save(
            buffer,
            format="WEBP",
            quality=90,
            exif=b"",
            icc_profile=None,
            xmp=b"",
        )
    return buffer.getvalue()


def prepare_media(upload):
    """Read, orient, strip and re-encode an uploaded image."""
    if upload.size and upload.size > MAX_IMAGE_BYTES:
        raise MediaRuleError(SIZE_ERROR)

    content = b"".join(upload.chunks())
    if len(content) > MAX_IMAGE_BYTES:
        raise MediaRuleError(SIZE_ERROR)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                if image_format not in FORMAT_TO_MIME:
                    raise MediaRuleError(FORMAT_ERROR)
                image.load()
                oriented = ImageOps.exif_transpose(image)
                width, height = oriented.size
                encoded = encode_image(oriented, image_format)
    except MediaRuleError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise MediaRuleError(FORMAT_ERROR) from error

    content_hash = hashlib.sha256(encoded).hexdigest()
    extension = FORMAT_TO_EXTENSION[image_format]
    return PreparedMedia(
        content=encoded,
        content_hash=content_hash,
        storage_key=f"{content_hash}.{extension}",
        mime_type=FORMAT_TO_MIME[image_format],
        width=width,
        height=height,
        metadata={"format": image_format, "bytes": len(encoded)},
    )


def store_media(store, upload, *, alt_text="", prepared=None):
    """Store an uploaded image for a store, reusing one already in it."""
    prepared = prepared or prepare_for_store(store, upload)
    existing = Media.objects.filter(store=store, content_hash=prepared.content_hash).first()
    if existing is not None:
        return existing

    storage = get_media_storage()
    if not storage.exists(prepared.storage_key):
        storage.save(
            prepared.storage_key,
            ContentFile(prepared.content, name=prepared.storage_key.rsplit("/", 1)[-1]),
        )

    return Media.objects.create(
        store=store,
        storage_key=prepared.storage_key,
        content_hash=prepared.content_hash,
        mime_type=prepared.mime_type,
        alt_text=alt_text,
        width=prepared.width,
        height=prepared.height,
        metadata=prepared.metadata,
    )


def prepare_for_store(store, upload):
    """Prepare an upload with a storage key under the store's id."""
    prepared = prepare_media(upload)
    return replace(
        prepared,
        storage_key=f"stores/{store.pk}/media/{prepared.storage_key}",
    )
