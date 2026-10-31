# Seeds the roles, permissions and matrix of ADR-0021.
# Never edit this migration after it is merged: change assignments in a new data migration.
# Values are literals, not imported constants, so this migration never changes when code does.

from django.db import migrations

PERMISSIONS = {
    "orders.place_manual": "Place a manual order on behalf of a customer.",
    "orders.refund": "Refund an order.",
    "inventory.adjust": "Adjust stock levels.",
    "catalog.manage": "Create and edit products and variants.",
    "social.approve_post": "Approve a social post for publishing.",
}

ROLE_PERMISSIONS = {
    "owner": [
        "orders.place_manual",
        "orders.refund",
        "inventory.adjust",
        "catalog.manage",
        "social.approve_post",
    ],
    "store_admin": [
        "orders.place_manual",
        "inventory.adjust",
        "catalog.manage",
        "social.approve_post",
    ],
    "content_editor": ["catalog.manage"],
    "warehouse": ["inventory.adjust"],
    "support": ["orders.place_manual"],
}


def seed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = {
        code: Permission.objects.create(code=code, description=description)
        for code, description in PERMISSIONS.items()
    }
    for name, codes in ROLE_PERMISSIONS.items():
        role = Role.objects.create(name=name)
        role.permissions.set([permissions[code] for code in codes])


def unseed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(name__in=ROLE_PERMISSIONS).delete()
    Permission.objects.filter(code__in=PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_store_memberships"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
