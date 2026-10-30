import pytest

from config import dependencies


@pytest.fixture
def override_store_resolver():
    """Back get_store_resolver() with the given resolver for one test."""

    def override(resolver):
        dependencies.override(dependencies.get_store_resolver, lambda: resolver)

    yield override
    dependencies.clear_overrides()
