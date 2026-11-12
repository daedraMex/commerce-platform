import re
from io import BytesIO

import pytest
from django.core.files.storage import storages
from PIL import Image

from apps.photos.domain.errors import ImageTooLarge, InvalidImage, TooManyPixels
from apps.photos.infrastructure.media_uploader import StorageMediaUploader
from apps.shared.domain.store import StoreReference
from tests.images import (
    heic_bytes,
    image_bytes,
    jpeg_with_exif,
    jpeg_with_icc_profile,
    non_srgb_profile,
    png_of_declared_pixels,
)

STORE = StoreReference(id=1, slug="home")


@pytest.fixture
def private_storage(tmp_path, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        },
    }
    settings.PHOTO_PREVIEW_LONG_SIDE = 800
    return tmp_path


@pytest.fixture
def uploader():
    return StorageMediaUploader()


def read_private(storage_key):
    with storages["private"].open(storage_key, "rb") as stored:
        return stored.read()


def open_private(storage_key):
    return Image.open(BytesIO(read_private(storage_key)))


def test_the_uploader_writes_a_store_scoped_original_and_preview(private_storage, uploader):
    result = uploader.upload(STORE, image_bytes(size=(12, 8)))

    assert re.fullmatch(r"stores/1/photos/originals/[0-9a-f]{32}\.jpg", result.original_key)
    assert re.fullmatch(r"stores/1/photos/previews/[0-9a-f]{32}\.jpg", result.preview_key)
    assert result.original_key != result.preview_key
    assert storages["private"].exists(result.original_key)
    assert storages["private"].exists(result.preview_key)


def test_the_original_is_a_metadata_free_jpeg(private_storage, uploader):
    result = uploader.upload(STORE, image_bytes(size=(12, 8)))

    with open_private(result.original_key) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert dict(image.getexif()) == {}
        assert "exif" not in image.info
        assert "icc_profile" not in image.info


def test_gps_metadata_is_stripped(private_storage, uploader):
    result = uploader.upload(STORE, jpeg_with_exif(size=(12, 8), gps=True))

    with open_private(result.original_key) as image:
        exif = image.getexif()
        assert dict(exif) == {}
        assert 0x8825 not in exif


def test_exif_orientation_is_applied(private_storage, uploader):
    result = uploader.upload(STORE, jpeg_with_exif(size=(12, 8), orientation=6))

    with open_private(result.original_key) as image:
        assert image.size == (8, 12)


def test_a_non_srgb_profile_is_converted_and_removed(private_storage, uploader):
    result = uploader.upload(
        STORE,
        jpeg_with_icc_profile(non_srgb_profile(), size=(12, 8), color=(200, 100, 50)),
    )

    with open_private(result.original_key) as image:
        assert image.mode == "RGB"
        assert "icc_profile" not in image.info


def test_a_decompression_bomb_is_a_domain_error(private_storage, uploader):
    content = png_of_declared_pixels(50_000_001)

    with pytest.raises(TooManyPixels) as error:
        uploader.upload(STORE, content)

    assert error.value.code == "too_many_pixels"


def test_an_upload_over_the_size_limit_is_rejected_before_decoding(private_storage, uploader):
    content = b"not an image" + b"x" * (25 * 1024 * 1024)

    with pytest.raises(ImageTooLarge) as error:
        uploader.upload(STORE, content)

    assert error.value.code == "too_large"


def test_an_unreadable_file_is_a_domain_error(private_storage, uploader):
    with pytest.raises(InvalidImage) as error:
        uploader.upload(STORE, b"definitely not an image")

    assert error.value.code == "invalid_image"


def test_a_heic_photo_is_decoded_and_encoded_as_jpeg(private_storage, uploader):
    result = uploader.upload(STORE, heic_bytes(size=(12, 8)))

    with open_private(result.original_key) as image:
        assert image.format == "JPEG"
        assert image.size == (12, 8)


def test_the_preview_is_downscaled_by_its_long_side(private_storage, settings, uploader):
    settings.PHOTO_PREVIEW_LONG_SIDE = 800

    result = uploader.upload(STORE, image_bytes(size=(2000, 1000)))

    with open_private(result.original_key) as original:
        assert original.size == (2000, 1000)
    with open_private(result.preview_key) as preview:
        assert preview.format == "JPEG"
        assert preview.size == (800, 400)
        assert dict(preview.getexif()) == {}


def test_a_preview_is_never_upscaled(private_storage, settings, uploader):
    settings.PHOTO_PREVIEW_LONG_SIDE = 800

    result = uploader.upload(STORE, image_bytes(size=(120, 80)))

    with open_private(result.preview_key) as preview:
        assert preview.size == (120, 80)


def test_another_store_gets_its_own_keys(private_storage, uploader):
    result = uploader.upload(StoreReference(id=2, slug="anime"), image_bytes())

    assert result.original_key.startswith("stores/2/photos/originals/")
    assert result.preview_key.startswith("stores/2/photos/previews/")
