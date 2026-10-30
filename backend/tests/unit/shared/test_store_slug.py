import pytest

from apps.shared.domain.store import is_valid_store_slug


@pytest.mark.parametrize(
    "slug",
    [
        "anime",
        "home",
        "a",
        "a" * 50,
        "anime-store-2",
        "2-store",
    ],
)
def test_accepts_well_formed_slugs(slug):
    assert is_valid_store_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "Anime",
        " anime",
        "anime ",
        "-anime",
        "anime-",
        "anime--store",
        "anime_store",
        "a" * 51,
        "anime\n",
        "anime store",
    ],
)
def test_rejects_malformed_slugs_without_normalizing(slug):
    assert not is_valid_store_slug(slug)
