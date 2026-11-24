import pytest

from apps.stores.models import Store
from apps.stores.services import get_store_by_slug

pytestmark = pytest.mark.django_db


def test_get_store_by_slug_returns_the_store_with_that_slug():
    home = Store.objects.create(slug="home", name="Home")
    Store.objects.create(slug="anime", name="Anime")

    assert get_store_by_slug("home") == home


def test_get_store_by_slug_returns_an_inactive_store_too():
    """The caller decides what an inactive store means (support.py rejects it)."""
    closed = Store.objects.create(slug="closed", name="Closed", is_active=False)

    assert get_store_by_slug("closed") == closed


def test_get_store_by_slug_returns_none_for_an_unknown_slug():
    Store.objects.create(slug="home", name="Home")

    assert get_store_by_slug("kawaii") is None
