from django.conf import settings

from config.celery import app


def test_celery_uses_the_redis_url_for_broker_and_results():
    assert app.conf.broker_url == settings.REDIS_URL
    assert app.conf.result_backend == settings.REDIS_URL


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
