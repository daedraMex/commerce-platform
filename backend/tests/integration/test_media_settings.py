import importlib

import environ
import pytest
from django.core.exceptions import ImproperlyConfigured

MEDIA_ENV_NAMES = (
    "R2_BUCKET_NAME",
    "R2_PRIVATE_BUCKET_NAME",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_REGION_NAME",
    "MEDIA_BASE_URL",
    "AWS_STORAGE_BUCKET_NAME",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_S3_ENDPOINT_URL",
)


@pytest.fixture
def settings_module(monkeypatch):
    import config.settings as module

    # Ignore the developer's own .env so the test controls every media variable.
    monkeypatch.setattr(environ.Env, "read_env", lambda *args, **kwargs: None)
    yield module
    monkeypatch.undo()
    importlib.reload(module)


def set_env(monkeypatch, **values):
    for name in MEDIA_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_r2_bucket_requires_a_media_base_url(settings_module, monkeypatch):
    set_env(monkeypatch, R2_BUCKET_NAME="bucket")

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_module)


def test_legacy_aws_names_are_not_media_fallbacks(settings_module, monkeypatch):
    set_env(monkeypatch, AWS_STORAGE_BUCKET_NAME="legacy")

    module = importlib.reload(settings_module)

    assert module.R2_BUCKET_NAME == ""
    assert module.STORAGES["default"]["BACKEND"].endswith("FileSystemStorage")


def test_filesystem_storage_defaults_media_base_url_to_the_local_route(
    settings_module, monkeypatch
):
    set_env(monkeypatch)

    module = importlib.reload(settings_module)

    assert module.STORAGES["default"]["BACKEND"].endswith("FileSystemStorage")
    assert module.MEDIA_BASE_URL == f"http://localhost:8000{module.MEDIA_URL}"


def test_filesystem_storage_keeps_private_media_outside_media_root(settings_module, monkeypatch):
    set_env(monkeypatch)

    module = importlib.reload(settings_module)

    private = module.STORAGES["private"]
    assert private["BACKEND"].endswith("FileSystemStorage")
    assert private["OPTIONS"]["location"] == module.BASE_DIR / "private-media"
    assert private["OPTIONS"]["location"] != module.MEDIA_ROOT
    assert module.PRIVATE_MEDIA_ROOT == module.BASE_DIR / "private-media"


def test_the_private_preview_long_side_defaults_to_1600(settings_module, monkeypatch):
    set_env(monkeypatch)

    module = importlib.reload(settings_module)

    assert module.PHOTO_PREVIEW_LONG_SIDE == 1600


def test_media_renditions_default_to_320_and_800_webp(settings_module, monkeypatch):
    set_env(monkeypatch)

    module = importlib.reload(settings_module)

    assert module.MEDIA_RENDITION_SIZES == {"thumbnail": 320, "medium": 800}
    assert module.MEDIA_RENDITION_VERSION == 1


def test_production_like_settings_use_r2_storage_for_both_buckets(settings_module, monkeypatch):
    set_env(
        monkeypatch,
        R2_BUCKET_NAME="catalog-media",
        R2_PRIVATE_BUCKET_NAME="catalog-private",
        R2_ACCESS_KEY_ID="key",
        R2_SECRET_ACCESS_KEY="secret",
        R2_ENDPOINT_URL="https://r2.example.com",
        MEDIA_BASE_URL="https://media.example.com",
    )

    module = importlib.reload(settings_module)

    assert module.MEDIA_BASE_URL == "https://media.example.com"
    storage = module.STORAGES["default"]
    assert storage["BACKEND"] == "storages.backends.s3.S3Storage"
    assert storage["OPTIONS"]["bucket_name"] == "catalog-media"
    assert storage["OPTIONS"]["querystring_auth"] is False

    private = module.STORAGES["private"]
    assert private["BACKEND"] == "storages.backends.s3.S3Storage"
    assert private["OPTIONS"]["bucket_name"] == "catalog-private"
    assert private["OPTIONS"]["default_acl"] is None
    assert private["OPTIONS"]["querystring_auth"] is False
    assert private["OPTIONS"]["object_parameters"] == {}


def test_a_public_bucket_requires_a_private_bucket_name(settings_module, monkeypatch):
    set_env(
        monkeypatch,
        R2_BUCKET_NAME="catalog-media",
        R2_ACCESS_KEY_ID="key",
        R2_SECRET_ACCESS_KEY="secret",
        R2_ENDPOINT_URL="https://r2.example.com",
        MEDIA_BASE_URL="https://media.example.com",
    )

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_module)


def test_the_public_and_private_buckets_must_be_different(settings_module, monkeypatch):
    set_env(
        monkeypatch,
        R2_BUCKET_NAME="catalog-media",
        R2_PRIVATE_BUCKET_NAME="catalog-media",
        R2_ACCESS_KEY_ID="key",
        R2_SECRET_ACCESS_KEY="secret",
        R2_ENDPOINT_URL="https://r2.example.com",
        MEDIA_BASE_URL="https://media.example.com",
    )

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_module)


def test_a_private_bucket_alone_uses_s3_only_for_private_media(settings_module, monkeypatch):
    set_env(
        monkeypatch,
        R2_PRIVATE_BUCKET_NAME="catalog-private",
        R2_ACCESS_KEY_ID="key",
        R2_SECRET_ACCESS_KEY="secret",
        R2_ENDPOINT_URL="https://r2.example.com",
    )

    module = importlib.reload(settings_module)

    assert module.STORAGES["default"]["BACKEND"].endswith("FileSystemStorage")
    private = module.STORAGES["private"]
    assert private["BACKEND"] == "storages.backends.s3.S3Storage"
    assert private["OPTIONS"]["bucket_name"] == "catalog-private"
