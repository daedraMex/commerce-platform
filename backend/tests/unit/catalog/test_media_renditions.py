from types import SimpleNamespace

from django.test import override_settings

from apps.catalog.media import rendition_key, rendition_url


def test_a_rendition_key_derives_from_the_storage_key_width_and_version():
    key = rendition_key("stores/1/media/abc123.jpg", width=320, version=1)

    assert key == "stores/1/media/renditions/abc123-320w-v1.webp"


def test_a_key_without_a_directory_still_lands_in_a_renditions_folder():
    key = rendition_key("abc123.png", width=800, version=2)

    assert key == "renditions/abc123-800w-v2.webp"


def test_a_leading_slash_does_not_repeat_in_the_rendition_key():
    key = rendition_key("/stores/1/media/abc123.webp", width=320, version=1)

    assert key == "stores/1/media/renditions/abc123-320w-v1.webp"


def test_each_width_writes_its_own_key():
    thumbnail = rendition_key("stores/1/media/abc123.jpg", width=320, version=1)
    medium = rendition_key("stores/1/media/abc123.jpg", width=800, version=1)

    assert thumbnail != medium


def test_a_version_bump_writes_a_new_key_for_every_width():
    before = rendition_key("stores/1/media/abc123.jpg", width=320, version=1)
    after = rendition_key("stores/1/media/abc123.jpg", width=320, version=2)

    assert before != after
    assert before.endswith("-320w-v1.webp")
    assert after.endswith("-320w-v2.webp")


def test_a_different_original_writes_different_rendition_keys():
    first = rendition_key("stores/1/media/first.jpg", width=320, version=1)
    second = rendition_key("stores/1/media/second.jpg", width=320, version=1)

    assert first != second


@override_settings(
    MEDIA_BASE_URL="https://media.example.com",
    MEDIA_RENDITION_SIZES={"thumbnail": 320, "medium": 800},
    MEDIA_RENDITION_VERSION=1,
)
def test_rendition_urls_follow_the_configured_sizes_and_version():
    media = SimpleNamespace(storage_key="stores/1/media/abc123.jpg")

    assert rendition_url(media, "thumbnail") == (
        "https://media.example.com/stores/1/media/renditions/abc123-320w-v1.webp"
    )
    assert rendition_url(media, "medium") == (
        "https://media.example.com/stores/1/media/renditions/abc123-800w-v1.webp"
    )


@override_settings(
    MEDIA_BASE_URL="https://media.example.com",
    MEDIA_RENDITION_SIZES={"thumbnail": 240, "medium": 800},
    MEDIA_RENDITION_VERSION=3,
)
def test_changing_the_settings_changes_the_rendition_url():
    media = SimpleNamespace(storage_key="stores/1/media/abc123.jpg")

    assert rendition_url(media, "thumbnail") == (
        "https://media.example.com/stores/1/media/renditions/abc123-240w-v3.webp"
    )
