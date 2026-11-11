import pytest
from django.conf import settings

from config import dependencies


@pytest.fixture(autouse=True)
def celery_eager(request):
    if request.node.get_closest_marker("no_celery_eager"):
        yield
        return

    from config.celery import app as celery_app

    original_settings = (
        settings.CELERY_TASK_ALWAYS_EAGER,
        settings.CELERY_TASK_EAGER_PROPAGATES,
    )
    original_conf = (
        celery_app.conf.task_always_eager,
        celery_app.conf.task_eager_propagates,
    )

    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    yield

    settings.CELERY_TASK_ALWAYS_EAGER, settings.CELERY_TASK_EAGER_PROPAGATES = original_settings
    celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates = original_conf


@pytest.fixture
def override_store_resolver():
    """Back get_store_resolver() with the given resolver for one test."""

    def override(resolver):
        dependencies.override(dependencies.get_store_resolver, lambda: resolver)

    yield override
    dependencies.clear_overrides()


@pytest.fixture
def override_authorizer():
    """Back get_authorizer() with the given authorizer for one test."""

    def override(authorizer):
        dependencies.override(dependencies.get_authorizer, lambda: authorizer)

    yield override
    dependencies.clear_overrides()


@pytest.fixture
def override_feature_flags():
    """Back get_feature_flags() with the given flags for one test."""

    def override(feature_flags):
        dependencies.override(dependencies.get_feature_flags, lambda: feature_flags)

    yield override
    dependencies.clear_overrides()
