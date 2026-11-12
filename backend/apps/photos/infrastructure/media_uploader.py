"""Normalize staff photos and store them in the private bucket (ADR-0028)."""

import warnings
from io import BytesIO
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from apps.photos.application.ports import UploadedPhoto
from apps.photos.domain.errors import ImageTooLarge, InvalidImage, TooManyPixels
from apps.shared.domain.store import StoreReference

register_heif_opener()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 50_000_000
PREVIEW_LONG_SIDE = 1600
JPEG_QUALITY = 90

# Make every Pillow decode in this process reject an image over our pixel limit.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def get_private_storage():
    """The configured private storage, reflecting the current settings."""
    config = settings.STORAGES.get("private", {})
    backend = config.get("BACKEND", "")
    options = dict(config.get("OPTIONS", {}))
    if backend == "django.core.files.storage.FileSystemStorage":
        options.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
        return FileSystemStorage(**options)
    return storages["private"]


def preview_long_side():
    """The configured long side of the single downscaled preview."""
    return int(getattr(settings, "PHOTO_PREVIEW_LONG_SIDE", PREVIEW_LONG_SIDE))


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


def flatten_to_rgb(image):
    """Return an opaque RGB image, flattening any alpha onto white."""
    if image.mode == "RGB":
        return image
    if "A" in image.getbands():
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def encode_jpeg(image):
    """Encode a metadata-free sRGB JPEG."""
    buffer = BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
        exif=b"",
        icc_profile=None,
        comment=b"",
    )
    return buffer.getvalue()


def downscale(image, long_side):
    """Shrink an image so its long side is ``long_side``, never upscaling it."""
    if max(image.size) <= long_side:
        return image
    scale = long_side / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def normalize(content: bytes) -> tuple[bytes, bytes, int, int]:
    """Decode, orient, convert, strip and encode an upload and its preview."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImageTooLarge("The photo is larger than 25 MB.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if width * height > MAX_PIXELS:
                    raise TooManyPixels("The photo has more than 50 megapixels.")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                converted = flatten_to_rgb(convert_to_srgb(oriented))
                original = encode_jpeg(converted)
                preview = encode_jpeg(downscale(converted, preview_long_side()))
                return original, preview, converted.width, converted.height
    except (ImageTooLarge, TooManyPixels):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise TooManyPixels("The photo has more than 50 megapixels.") from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise InvalidImage("The file is not an image this service can read.") from error


class StorageMediaUploader:
    """The MediaUploader adapter: private storage plus Pillow normalization."""

    def upload(self, store: StoreReference, content: bytes) -> UploadedPhoto:
        original, preview, width, height = normalize(content)
        storage = get_private_storage()
        original_key = f"stores/{store.id}/photos/originals/{uuid4().hex}.jpg"
        preview_key = f"stores/{store.id}/photos/previews/{uuid4().hex}.jpg"
        original_key = storage.save(
            original_key, ContentFile(original, name=original_key.rsplit("/", 1)[-1])
        )
        preview_key = storage.save(
            preview_key, ContentFile(preview, name=preview_key.rsplit("/", 1)[-1])
        )
        return UploadedPhoto(
            original_key=original_key,
            preview_key=preview_key,
            width=width,
            height=height,
        )
