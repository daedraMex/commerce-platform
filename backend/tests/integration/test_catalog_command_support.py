import pytest
from django.core.management.base import CommandError

from apps.catalog.management.support import get_active_store
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def test_get_active_store_returns_an_active_store():
    home = Store.objects.create(slug="home", name="Home")

    assert get_active_store("home") == home


def test_get_active_store_rejects_an_unknown_slug():
    with pytest.raises(CommandError, match=r"^No store with slug 'kawaii'\.$"):
        get_active_store("kawaii")


def test_get_active_store_rejects_an_inactive_store():
    Store.objects.create(slug="closed", name="Closed", is_active=False)

    with pytest.raises(CommandError, match=r"^Store 'closed' is inactive\.$"):
        get_active_store("closed")
