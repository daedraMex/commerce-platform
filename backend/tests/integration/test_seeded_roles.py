from pathlib import Path

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Permission, Role

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "apps" / "accounts" / "migrations"
SCHEMA_MIGRATION = "0002_store_memberships"
SEED_MIGRATION = "0003_seed_roles_and_permissions"

# Copied from the ADR-0021 table by hand, so the test never derives it from the migration.
ADR_0021_MATRIX = {
    "owner": {
        "orders.place_manual",
        "orders.refund",
        "inventory.adjust",
        "catalog.manage",
        "social.approve_post",
    },
    "store_admin": {
        "orders.place_manual",
        "inventory.adjust",
        "catalog.manage",
        "social.approve_post",
    },
    "content_editor": {"catalog.manage"},
    "warehouse": {"inventory.adjust"},
    "support": {"orders.place_manual"},
}


def seeded_matrix():
    return {
        role.name: {permission.code for permission in role.permissions.all()}
        for role in Role.objects.prefetch_related("permissions")
    }


@pytest.mark.django_db
def test_the_seeded_matrix_equals_adr_0021_role_by_role():
    assert seeded_matrix() == ADR_0021_MATRIX


@pytest.mark.django_db
def test_every_seeded_permission_is_described():
    assert set(Permission.objects.values_list("code", flat=True)) == set().union(
        *ADR_0021_MATRIX.values()
    )
    assert not Permission.objects.filter(description="").exists()


def test_the_schema_and_the_seed_are_separate_migration_files():
    assert (MIGRATIONS_DIR / f"{SCHEMA_MIGRATION}.py").is_file()
    assert (MIGRATIONS_DIR / f"{SEED_MIGRATION}.py").is_file()


# serialized_rollback restores the seeded rows that the reversal deletes, for later tests.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_the_seed_migration_reverses_cleanly_and_reapplies():
    executor = MigrationExecutor(connection)
    executor.migrate([("accounts", SCHEMA_MIGRATION)])

    assert not Role.objects.exists()
    assert not Permission.objects.exists()

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([("accounts", SEED_MIGRATION)])

    assert seeded_matrix() == ADR_0021_MATRIX
