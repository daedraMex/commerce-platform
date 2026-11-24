"""A module never imports another module's models or infrastructure.

It goes through services or ports. CRUD modules keep their models in ``models.py``;
modules with business rules keep them in ``infrastructure/`` (AGENTS.md).

Besides imports, three ways around the import check are refused (#178), with names
resolved through the file's imports (aliases, ``from apps.x import models as m``,
full dotted paths):

- the app registry: ``apps.get_model("stores", "Store")``, the keyword form, and
  ``apps.get_app_config("stores").get_model(...)``, with another module's label;
- a re-export: a name reached through the module's own ``models`` or
  ``infrastructure`` that is really another module's model (``models.py`` may
  import it for a foreign key);
- in ``admin.py`` or ``models.py``, which may read and wire other modules' models,
  a write through one of their managers (``objects``, ``_default_manager``,
  ``_base_manager``: ``Store.objects.update(...)``).

Accepted, because telling them apart needs types or running the code: writes
through an instance (``store.save()``) or an admin action's ``queryset`` (whose
model the admin chose), and models looked up at runtime (a variable label in
``get_model``, ``apps.all_models[...]``, ``ContentType.model_class()``).
"""

import ast
import importlib

from tests.architecture.support import (
    APPS_DIR,
    dotted,
    import_aliases,
    parse,
    relative,
    resolved,
    source_files,
)

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


MANAGERS = {"objects", "_default_manager", "_base_manager"}


def _registry_label(call):
    """The app label of an app-registry ``get_model`` call, or None if it is not one."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "get_model"):
        return None
    owner = call.func.value
    if isinstance(owner, ast.Call) and dotted(owner.func) in {
        "apps.get_app_config",
        "django.apps.apps.get_app_config",
    }:
        label = owner.args[0] if owner.args else None  # get_app_config("x").get_model("M")
    elif dotted(owner) in {"apps", "django.apps.apps"}:
        label = next((k.value for k in call.keywords if k.arg == "app_label"), None)
        label = call.args[0] if call.args else label
    else:
        return None  # another object's get_model (an SDK client): not the app registry
    if isinstance(label, ast.Constant) and isinstance(label.value, str):
        return label.value
    return None


def foreign_get_model_calls(path, own_module):
    """App-registry ``get_model`` with another module's label, in every signature."""
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Call):
            label = _registry_label(node)
            if label is not None and label.split(".", 1)[0] != own_module:
                yield node.lineno, label


def _resolve(module_name, name):
    obj = getattr(importlib.import_module(module_name), name, None)
    return getattr(obj, "__module__", None)


def _own_internal_name(name, own_module):
    """``(module, attribute)`` for ``apps.<own>.models.X`` or ``...infrastructure...X``."""
    parts = name.split(".")
    if parts[:2] != ["apps", own_module] or len(parts) < 4:
        return None
    if parts[2] == "models":
        cut = 3  # apps.<own>.models.<Name>[.objects...]
    elif parts[2] == "infrastructure":
        cut = 4 if len(parts) >= 5 else 3  # apps.<own>.infrastructure.<module>.<Name>
    else:
        return None
    return ".".join(parts[:cut]), parts[cut]


def reexported_foreign_models(path, own_module, resolve=_resolve):
    """Names reached through the module's own models that another module defines."""
    tree = parse(path)
    aliases = import_aliases(tree)
    candidates = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Attribute):
            name = resolved(node, aliases)
            names = [name] if name else []
        else:
            continue
        for name in names:
            target = _own_internal_name(name, own_module)
            if target is not None:
                candidates.setdefault(target, node.lineno)
    for (module, attribute), line in sorted(candidates.items(), key=lambda item: item[1]):
        defined_in = resolve(module, attribute) or ""
        owner = defined_in.split(".")
        if len(owner) >= 2 and owner[0] == "apps" and owner[1] != own_module:
            yield line, f"{module}.{attribute} is {defined_in}"


def _manager_owner(node):
    """The model expression a manager write goes through (``Store`` in ``Store.objects``)."""
    while isinstance(node, ast.Attribute | ast.Call):
        if isinstance(node, ast.Attribute) and node.attr in MANAGERS:
            return node.value
        node = node.func if isinstance(node, ast.Call) else node.value
    return None


def foreign_manager_writes(path, own_module):
    """A write through another module's model manager, however the model is named."""
    tree = parse(path)
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MANAGER_WRITES
        ):
            continue
        owner = _manager_owner(node.func.value)
        model = resolved(owner, aliases) if owner is not None else None
        if model and _is_foreign_internal(model, own_module):
            yield node.lineno, f"{model} ...{node.func.attr}()"


def test_the_scan_sees_get_model_with_another_modules_label(tmp_path):
    planted = tmp_path / "services.py"
    planted.write_text(
        "from django.apps import apps\n"
        "Store = apps.get_model('stores', 'Store')\n"
        "Other = apps.get_model('stores.Store')\n"
        "Mine = apps.get_model('catalog', 'Product')\n"
        "Kw = apps.get_model(app_label='stores', model_name='Store')\n"
        "import django.apps\n"
        "Full = django.apps.apps.get_model('accounts', 'User')\n"
        "Cfg = apps.get_app_config('stores').get_model('Store')\n"
        "OwnCfg = apps.get_app_config('catalog').get_model('Product')\n"
        "llm = client.get_model('gemini-2.0-flash')\n"
    )

    assert list(foreign_get_model_calls(planted, "catalog")) == [
        (2, "stores"),
        (3, "stores.Store"),
        (5, "stores"),
        (7, "accounts"),
        (8, "stores"),
    ]


def test_the_scan_sees_another_modules_model_re_exported_through_models(tmp_path):
    planted = tmp_path / "services.py"
    planted.write_text(
        "from apps.catalog.models import Product, Store\n"
        "from apps.catalog import models as cm\n"
        "cm.Membership\n"
        "import apps.catalog.models\n"
        "apps.catalog.models.User\n"
    )
    defined = {
        "Product": "apps.catalog.models",
        "Store": "apps.stores.models",
        "Membership": "apps.accounts.models",
        "User": "apps.accounts.models",
    }

    found = list(
        reexported_foreign_models(planted, "catalog", resolve=lambda _m, name: defined[name])
    )

    assert found == [
        (1, "apps.catalog.models.Store is apps.stores.models"),
        (3, "apps.catalog.models.Membership is apps.accounts.models"),
        (5, "apps.catalog.models.User is apps.accounts.models"),
    ]


def test_the_scan_sees_an_admin_that_writes_another_modules_model(tmp_path):
    planted = tmp_path / "admin.py"
    planted.write_text(
        "from apps.stores.models import Store\n"
        "from apps.accounts.models import User\n"
        "def close(modeladmin, request, queryset):\n"
        "    Store.objects.filter(pk__in=queryset).update(is_active=False)\n"
        "    User.objects.create(email='x')\n"
        "    Store.objects.filter(slug='x').exists()\n"
        "    queryset.update(is_active=False)\n"  # accepted: the admin chose the model
        "    Store._default_manager.update(is_active=False)\n"
        "    from apps.stores import models as sm\n"
        "    sm.Store.objects.create(slug='y')\n"
        "    import apps.stores.models\n"
        "    apps.stores.models.Store.objects.all().delete()\n"
    )

    assert [line for line, _ in foreign_manager_writes(planted, "accounts")] == [4, 8, 10, 12]


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
