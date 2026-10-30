import pytest

from apps.shared.domain.store import is_valid_store_slug
from tests.store_slugs import INVALID_STORE_SLUGS, VALID_STORE_SLUGS


@pytest.mark.parametrize("slug", VALID_STORE_SLUGS)
def test_accepts_well_formed_slugs(slug):
    assert is_valid_store_slug(slug)


@pytest.mark.parametrize("slug", INVALID_STORE_SLUGS)
def test_rejects_malformed_slugs_without_normalizing(slug):
    assert not is_valid_store_slug(slug)
