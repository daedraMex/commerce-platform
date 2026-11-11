"""Store public product images and build their public URLs."""

import hashlib
import warnings
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from apps.catalog.models import Media

MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_RENDITION_SIZES = {"thumbnail": 320, "medium": 800}
DEFAULT_RENDITION_VERSION = 1
RENDITION_FORMAT = "WEBP"
RENDITION_QUALITY = 82
RENDITION_METHOD = 6
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


@dataclass(frozen=True)
class PreparedMediaFile:
    """What the first import pass keeps about a file: metadata, never its bytes."""

    path: Path
    content_hash: str
    storage_key: str
    mime_type: str
    width: int
    height: int
    metadata: dict


@dataclass(frozen=True)
class Rendition:
    """One derived WebP file, whether it was just written or already existed."""

    name: str
    width: int
    storage_key: str
    written: bool


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


def rendition_sizes():
    """The named rendition widths, from settings so a change writes new keys."""
    return dict(getattr(settings, "MEDIA_RENDITION_SIZES", DEFAULT_RENDITION_SIZES))


def rendition_version():
    """The encoding version mixed into every rendition key."""
    return int(getattr(settings, "MEDIA_RENDITION_VERSION", DEFAULT_RENDITION_VERSION))


def rendition_key(storage_key, *, width, version):
    """Derive a rendition key from the original's key, the width and the version."""
    path = PurePosixPath(storage_key.lstrip("/"))
    name = f"{path.stem}-{width}w-v{version}.webp"
    parent = path.parent
    if str(parent) == ".":
        return str(PurePosixPath("renditions", name))
    return str(parent / "renditions" / name)


def rendition_url(media, name):
    """The public URL of one named rendition of a Media."""
    width = rendition_sizes()[name]
    key = rendition_key(media.storage_key, width=width, version=rendition_version())
    return media_url(key)


def resize_to_width(image, width):
    """Shrink an image to a width, keeping its ratio and never upscaling it."""
    if image.width <= width:
        return image
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def encode_rendition(image):
    """Encode a resized image as a metadata-free WebP."""
    image = convert_to_srgb(image)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    buffer = BytesIO()
    image.save(
        buffer,
        format=RENDITION_FORMAT,
        quality=RENDITION_QUALITY,
        method=RENDITION_METHOD,
        exif=b"",
        icc_profile=None,
        xmp=b"",
    )
    return buffer.getvalue()


def rendition_payload(content, width):
    """Build the WebP bytes for one rendition width from an original image."""
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            oriented = ImageOps.exif_transpose(image)
            return encode_rendition(resize_to_width(oriented, width))
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise MediaRuleError("The stored image cannot be read for renditions.") from error


def store_renditions(storage_key, *, content=None):
    """Write every missing rendition for a stored original and return what happened.

    An existing rendition is never rewritten: rendition keys are served with an
    immutable cache, so changing the bytes under a key would leave stale copies
    cached. To change the encoding, bump MEDIA_RENDITION_VERSION for new keys.
    """
    storage = get_media_storage()
    if content is None:
        try:
            with storage.open(storage_key, "rb") as stored:
                content = stored.read()
        except OSError as error:
            raise MediaRuleError(f"Cannot read the stored image {storage_key!r}.") from error

    version = rendition_version()
    renditions = []
    for name, width in sorted(rendition_sizes().items(), key=lambda item: item[1]):
        key = rendition_key(storage_key, width=width, version=version)
        if storage.exists(key):
            renditions.append(Rendition(name, width, key, False))
            continue

        payload = rendition_payload(content, width)
        saved_key = storage.save(key, ContentFile(payload, name=key.rsplit("/", 1)[-1]))
        if saved_key != key:
            storage.delete(saved_key)
            raise MediaRuleError(
                f"The rendition {key!r} was stored as {saved_key!r}; refusing to keep it."
            )
        renditions.append(Rendition(name, width, key, True))
    return renditions


def convert_to_srgb(image):
    """Convert an image with an embedded ICC profile to sRGB."""
    profile = image.info.get("icc_profile")
    if not profile:
        return image
    try:
        source = ImageCms.ImageCmsProfile(BytesIO(profile))
        target = ImageCms.createProfile("sRGB")
        output_mode = "RGBA" if image.mode in ("RGBA", "LA") else "RGB"
        return ImageCms.profileToProfile(image, source, target, outputMode=output_mode)
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return image


def encode_image(image, image_format):
    """Re-encode an image with no EXIF, XMP, ICC or text metadata."""
    image = convert_to_srgb(image)
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


def save_prepared_media(prepared):
    """Write a prepared image and its renditions once; its key is content-addressed."""
    storage = get_media_storage()
    if not storage.exists(prepared.storage_key):
        storage.save(
            prepared.storage_key,
            ContentFile(prepared.content, name=prepared.storage_key.rsplit("/", 1)[-1]),
        )
    store_renditions(prepared.storage_key, content=prepared.content)


def media_from_prepared(store, prepared, *, alt_text=""):
    """Build, but do not save, the Media a prepared image describes."""
    return Media(
        store=store,
        storage_key=prepared.storage_key,
        content_hash=prepared.content_hash,
        mime_type=prepared.mime_type,
        alt_text=alt_text,
        width=prepared.width,
        height=prepared.height,
        metadata=prepared.metadata,
    )


def store_media(store, upload, *, alt_text="", prepared=None):
    """Store an uploaded image for a store, reusing one already in it."""
    prepared = prepared or prepare_for_store(store, upload)
    existing = Media.objects.filter(store=store, content_hash=prepared.content_hash).first()
    if existing is not None:
        return existing

    save_prepared_media(prepared)
    media = media_from_prepared(store, prepared, alt_text=alt_text)
    media.save()
    return media


def prepare_for_store(store, upload):
    """Prepare an upload with a storage key under the store's id."""
    prepared = prepare_media(upload)
    return replace(
        prepared,
        storage_key=f"stores/{store.pk}/media/{prepared.storage_key}",
    )


def prepare_path_for_store(store, path):
    """Read, validate and re-encode an image file with the store's storage key."""
    try:
        size = path.stat().st_size
    except OSError as error:
        raise MediaRuleError(f"Cannot read the file {path.name!r}.") from error
    if size > MAX_IMAGE_BYTES:
        raise MediaRuleError(SIZE_ERROR)

    try:
        with path.open("rb") as image_file:
            upload = SimpleUploadedFile(path.name, image_file.read())
    except OSError as error:
        raise MediaRuleError(f"Cannot read the file {path.name!r}.") from error
    return prepare_for_store(store, upload)


def prepare_media_file(store, path):
    """Read and validate an image file, keeping only the metadata the plan needs."""
    prepared = prepare_path_for_store(store, path)
    return PreparedMediaFile(
        path=path,
        content_hash=prepared.content_hash,
        storage_key=prepared.storage_key,
        mime_type=prepared.mime_type,
        width=prepared.width,
        height=prepared.height,
        metadata=prepared.metadata,
    )
