import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

APP = "token_blacklist"
TABLES = {"token_blacklist_outstandingtoken", "token_blacklist_blacklistedtoken"}


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)


def _blacklist_tables():
    return TABLES & set(connection.introspection.table_names())


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_token_blacklist_migrations_are_reversible():
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes(APP)

    _migrate([(APP, None)])
    assert _blacklist_tables() == set()

    _migrate(latest)
    assert _blacklist_tables() == TABLES
