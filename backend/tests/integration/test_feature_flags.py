import pytest

from apps.shared.domain.store import StoreReference
from apps.stores.models import Store, StoreFeatureFlag
from config.dependencies import get_feature_flags

pytestmark = pytest.mark.django_db

FLAG = "instagram-publishing"


def reference(store):
    return StoreReference(id=store.id, slug=store.slug)


def test_a_flag_with_no_row_is_off(store):
    assert get_feature_flags().is_enabled(reference(store), FLAG) is False


def test_an_enabled_flag_is_on(store):
    StoreFeatureFlag.objects.create(store=store, code=FLAG, enabled=True)

    assert get_feature_flags().is_enabled(reference(store), FLAG) is True


def test_a_disabled_row_is_off(store):
    StoreFeatureFlag.objects.create(store=store, code=FLAG, enabled=False)

    assert get_feature_flags().is_enabled(reference(store), FLAG) is False


def test_a_flag_enabled_in_one_store_is_off_in_another(store):
    anime = Store.objects.create(slug="anime", name="Anime")
    StoreFeatureFlag.objects.create(store=store, code=FLAG, enabled=True)

    assert get_feature_flags().is_enabled(reference(anime), FLAG) is False
