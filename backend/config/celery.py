import importlib.util
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")


def _interfaces_packages():
    """Every installed app's interfaces package, where business modules keep their tasks."""
    from django.apps import apps

    return [
        f"{config.name}.interfaces"
        for config in apps.get_app_configs()
        if importlib.util.find_spec(f"{config.name}.interfaces") is not None
    ]


# CRUD-only modules keep tasks in apps/<module>/tasks.py; modules with business rules keep
# them in apps/<module>/interfaces/tasks.py (AGENTS.md). The worker must load both.
app.autodiscover_tasks()
app.autodiscover_tasks(_interfaces_packages)
