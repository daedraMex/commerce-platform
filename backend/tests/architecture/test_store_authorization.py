"""Store actions are authorized through the Authorizer port, never Django's permissions.

``has_perm()``, Django's ``auth.Permission`` and DRF's model-permission classes only
gate the admin (AGENTS.md). Beyond direct calls, the scan refuses the ways around a
call check found in #178: reading the method without calling it
(``check = user.has_perm``), naming it in a string (``getattr(user, "has_perm")``),
DRF's ``DjangoModelPermissions`` family and reaching ``auth.Permission`` through
any import (``from django.contrib.auth import models as m; m.Permission``).
Accepted, because only running the code could tell: building the name at runtime
(``"has_" + "perm"``). ``apps.accounts.models.Permission`` is the roles model and
stays allowed.
"""

import ast

from tests.architecture.support import import_aliases, parse, relative, resolved, source_files

# Django's permissions only gate the admin.
ALLOWED_FILE_NAMES = {"admin.py"}
BANNED_METHODS = {"has_perm", "has_perms"}
BANNED_PERMISSION_CLASSES = {
    "DjangoModelPermissions",
    "DjangoModelPermissionsOrAnonReadOnly",
    "DjangoObjectPermissions",
}
AUTH_MODELS = "django.contrib.auth.models"
AUTH_PERMISSION = f"{AUTH_MODELS}.Permission"


def django_permission_uses(path):
    tree = parse(path)
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and resolved(node, aliases) == AUTH_PERMISSION:
            yield node.lineno, AUTH_PERMISSION
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_METHODS:
            yield node.lineno, node.attr
        elif isinstance(node, ast.Constant) and node.value in BANNED_METHODS:
            yield node.lineno, f"{node.value!r}"
        elif isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in BANNED_PERMISSION_CLASSES:
                yield node.lineno, name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if f"{node.module}.{alias.name}" == AUTH_PERMISSION:
                    yield node.lineno, AUTH_PERMISSION
                elif alias.name in BANNED_PERMISSION_CLASSES:
                    yield node.lineno, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == AUTH_MODELS:
                    yield node.lineno, AUTH_MODELS


def test_the_scan_sees_every_way_around_a_has_perm_call(tmp_path):
    planted = tmp_path / "views.py"
    planted.write_text(
        "from django.contrib.auth.models import Permission\n"
        "import django.contrib.auth.models\n"
        "from rest_framework.permissions import DjangoModelPermissions\n"
        "user.has_perm('catalog.change_product')\n"
        "check = user.has_perms\n"
        "getattr(user, 'has_perm')('x')\n"
        "permission_classes = [DjangoObjectPermissions]\n"
        "def has_permission(self, request, view): ...\n"
        "from django.contrib.auth import models as auth_models\n"
        "auth_models.Permission.objects.all()\n"
        "from django.contrib import auth\n"
        "auth.models.Permission\n"
        "from apps.accounts.models import Permission as RolePermission\n"
        '"""A docstring that mentions has_perm is fine."""\n'
    )

    assert sorted({line for line, _ in django_permission_uses(planted)}) == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        10,
        12,
    ]


def test_no_django_permissions_outside_the_admin():
    found = [
        f"{relative(path)}:{line} {what}"
        for path in source_files()
        if path.name not in ALLOWED_FILE_NAMES
        for line, what in django_permission_uses(path)
    ]

    assert found == [], "Authorize store actions with the Authorizer port, not has_perm()."
