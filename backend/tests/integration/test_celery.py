import pytest
from django.conf import settings

from config.celery import app


def test_celery_uses_the_redis_url_for_broker():
    assert app.conf.broker_url == settings.REDIS_URL


def test_celery_ignores_task_results():
    assert settings.CELERY_TASK_IGNORE_RESULT is True
    assert app.conf.task_ignore_result is True
    assert app.conf.result_backend is None


@pytest.mark.no_celery_eager
def test_celery_defaults_to_not_eager():
    assert settings.CELERY_TASK_ALWAYS_EAGER is False
    assert app.conf.task_always_eager is False


def test_celery_runs_eagerly_during_tests():
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
    assert app.conf.task_always_eager is True
    assert app.conf.task_eager_propagates is True


def test_celery_discovers_tasks_from_installed_apps():
    app.loader.import_default_modules()

    assert "apps.health.tasks.smoke" in app.tasks


def test_smoke_task_runs_inline():
    from apps.health.tasks import smoke

    result = smoke.delay()

    assert result.get() == "ok"
