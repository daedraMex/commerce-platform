import importlib

from django.urls import clear_url_caches

FILESYSTEM_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def test_debug_serves_uploaded_media_from_the_local_filesystem(client, settings, tmp_path):
    import config.urls

    original = (settings.DEBUG, settings.MEDIA_ROOT, settings.STORAGES)
    try:
        settings.DEBUG = True
        settings.MEDIA_ROOT = tmp_path
        settings.STORAGES = FILESYSTEM_STORAGES
        (tmp_path / "photo.jpg").write_bytes(b"stored-image-bytes")
        importlib.reload(config.urls)
        clear_url_caches()

        response = client.get("/media/photo.jpg")

        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"stored-image-bytes"
    finally:
        settings.DEBUG, settings.MEDIA_ROOT, settings.STORAGES = original
        importlib.reload(config.urls)
        clear_url_caches()
