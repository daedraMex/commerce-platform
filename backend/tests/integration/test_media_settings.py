import importlib

import environ
import pytest
from django.core.exceptions import ImproperlyConfigured

MEDIA_ENV_NAMES = (
    "R2_BUCKET_NAME",
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
