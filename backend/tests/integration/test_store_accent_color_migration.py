import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.stores.models import ACCENT_COLOR_DEFAULT, Store

BEFORE = ("stores", "0002_store_feature_flag")
AFTER = ("stores", "0003_store_accent_color")


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_existing_stores_receive_the_default_accent_color_when_the_migration_runs():
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE])
    old_apps = executor.loader.project_state([BEFORE]).apps
    old_store = old_apps.get_model("stores", "Store")
    old_store.objects.create(slug="home", name="Home")

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([AFTER])

    assert Store.objects.get(slug="home").accent_color == ACCENT_COLOR_DEFAULT
