"""A module never imports another module's models or infrastructure.

It goes through services or ports. CRUD modules keep their models in ``models.py``;
modules with business rules keep them in ``infrastructure/`` (AGENTS.md).

Besides imports, three ways around the import check are refused (#178):
``apps.get_model("stores", "Store")`` with another module's label; a name imported
from the module's own ``models`` or ``infrastructure`` that is really another
module's model (a re-export through ``models.py``, which may import it for a
foreign key); and an ``admin.py`` or ``models.py`` that writes another module's
model through its manager (``Store.objects.update(...)``), since their allowance
is to read and wire those models, not to change them. Writes through an instance
(``store.save()``) in those two files are accepted: the admin saves the inlines
it wires through Django's own machinery, and telling them apart needs types.
"""

import ast
import importlib

from tests.architecture.support import APPS_DIR, parse, relative, source_files

# Foreign keys need the other module's model, and the Django admin wires inlines
# across modules (accounts registers the Store admin with its memberships).
ALLOWED_FILE_NAMES = {"models.py", "admin.py"}
# Existing violations, each tracked by an issue. Remove an entry when it is fixed.
EXCEPTIONS: dict[str, str] = {}


def _is_foreign_internal(name, own_module):
    parts = name.split(".")
    return (
        len(parts) >= 3
        and parts[0] == "apps"
        and parts[1] != own_module
        and parts[2] in {"models", "infrastructure"}
    )


def foreign_model_imports(path, own_module):
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            if _is_foreign_internal(name, own_module):
                yield name
                break


def violations():
    found = {}
    for path in source_files():
        if path.name in ALLOWED_FILE_NAMES:
            continue
        own_module = path.relative_to(APPS_DIR).parts[0]
        imports = sorted(set(foreign_model_imports(path, own_module)))
        if imports:
            found[relative(path)] = imports
    return found


MANAGER_WRITES = {
    "create",
    "bulk_create",
    "get_or_create",
    "update_or_create",
    "update",
    "bulk_update",
    "delete",
}


def _own_module(path):
    return path.relative_to(APPS_DIR).parts[0]


def foreign_get_model_calls(path, own_module):
    """``apps.get_model`` with another module's app label, in either signature."""
    for node in ast.walk(parse(path)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_model"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        label = node.args[0].value.split(".", 1)[0]
        if label != own_module:
            yield node.lineno, node.args[0].value


def _resolve(module_name, name):
    obj = getattr(importlib.import_module(module_name), name, None)
    return getattr(obj, "__module__", None)


def reexported_foreign_models(path, own_module, resolve=_resolve):
    """Names imported from the module's own models that another module defines."""
    for node in ast.walk(parse(path)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        if not (len(parts) >= 3 and parts[:2] == ["apps", own_module]):
            continue
        if parts[2] not in {"models", "infrastructure"}:
            continue
        for alias in node.names:
            defined_in = resolve(node.module, alias.name) or ""
            owner = defined_in.split(".")
            if len(owner) >= 2 and owner[0] == "apps" and owner[1] != own_module:
                yield node.lineno, f"{node.module}.{alias.name} is {defined_in}"


def _foreign_model_names(tree, own_module):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if _is_foreign_internal(node.module, own_module):
                names |= {alias.asname or alias.name for alias in node.names}
    return names


def _root_name(node):
    while isinstance(node, ast.Attribute | ast.Call):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _goes_through_objects(node):
    while isinstance(node, ast.Attribute | ast.Call):
        if isinstance(node, ast.Attribute) and node.attr == "objects":
            return True
        node = node.func if isinstance(node, ast.Call) else node.value
    return False


def foreign_manager_writes(path, own_module):
    """``Foreign.objects....<write>()`` on a model imported from another module."""
    tree = parse(path)
    foreign = _foreign_model_names(tree, own_module)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MANAGER_WRITES
            and _goes_through_objects(node.func.value)
            and _root_name(node.func.value) in foreign
        ):
            yield node.lineno, f"{_root_name(node.func.value)}.objects...{node.func.attr}()"


def test_the_scan_sees_get_model_with_another_modules_label(tmp_path):
    planted = tmp_path / "services.py"
    planted.write_text(
        "from django.apps import apps\n"
        "Store = apps.get_model('stores', 'Store')\n"
        "Other = apps.get_model('stores.Store')\n"
        "Mine = apps.get_model('catalog', 'Product')\n"
    )

    assert list(foreign_get_model_calls(planted, "catalog")) == [
        (2, "stores"),
        (3, "stores.Store"),
    ]


def test_the_scan_sees_another_modules_model_re_exported_through_models(tmp_path):
    planted = tmp_path / "services.py"
    planted.write_text("from apps.catalog.models import Product, Store\n")
    defined = {"Product": "apps.catalog.models", "Store": "apps.stores.models"}

    found = list(
        reexported_foreign_models(planted, "catalog", resolve=lambda _m, name: defined[name])
    )

    assert found == [(1, "apps.catalog.models.Store is apps.stores.models")]


def test_the_scan_sees_an_admin_that_writes_another_modules_model(tmp_path):
    planted = tmp_path / "admin.py"
    planted.write_text(
        "from apps.stores.models import Store\n"
        "from apps.accounts.models import User\n"
        "def close(modeladmin, request, queryset):\n"
        "    Store.objects.filter(pk__in=queryset).update(is_active=False)\n"
        "    User.objects.create(email='x')\n"
        "    Store.objects.filter(slug='x').exists()\n"
        "    queryset.update(is_active=False)\n"
    )

    assert [line for line, _ in foreign_manager_writes(planted, "accounts")] == [4]


def test_no_module_reaches_another_modules_models_another_way():
    found = []
    for path in source_files():
        own = _own_module(path)
        found += [
            f"{relative(path)}:{n} get_model({w})" for n, w in foreign_get_model_calls(path, own)
        ]
        if path.name in ALLOWED_FILE_NAMES:
            found += [
                f"{relative(path)}:{n} writes {w}" for n, w in foreign_manager_writes(path, own)
            ]
        else:
            found += [f"{relative(path)}:{n} {w}" for n, w in reexported_foreign_models(path, own)]

    assert found == [], "Use the other module's services or ports instead of its models."


def test_the_scan_sees_models_and_infrastructure_imports(tmp_path):
    planted = tmp_path / "views_extra.py"
    planted.write_text(
        "from apps.photos.infrastructure.models import PhotoSubmission\n"
        "import apps.stores.models as store_models\n"
        "from apps.catalog import models\n"
        "from apps.catalog.models import Product\n"
    )

    assert sorted(foreign_model_imports(planted, "catalog")) == [
        "apps.photos.infrastructure.models",
        "apps.stores.models",
    ]


def test_no_module_imports_another_modules_models():
    unexpected = {path: names for path, names in violations().items() if path not in EXCEPTIONS}

    assert unexpected == {}, (
        "Use the other module's services or ports instead of its models or "
        f"infrastructure: {unexpected}"
    )


def test_every_exception_is_still_a_violation():
    # A fixed exception must leave the list, so the guard covers that file again.
    assert set(EXCEPTIONS) <= set(violations())
