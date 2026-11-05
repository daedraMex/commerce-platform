import importlib

import pytest
from django.contrib.postgres.operations import UnaccentExtension
from django.db import connection

pytestmark = pytest.mark.django_db


def test_the_unaccent_migration_uses_a_reversible_operation():
    migration = importlib.import_module("apps.catalog.migrations.0003_unaccent")

    assert any(
        isinstance(operation, UnaccentExtension) and operation.reversible
        for operation in migration.Migration.operations
    )


def test_the_test_database_has_the_unaccent_extension():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'unaccent'")

        assert cursor.fetchone() == (1,)
