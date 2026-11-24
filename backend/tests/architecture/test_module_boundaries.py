"""A module never imports another module's models or infrastructure.

It goes through services or ports. CRUD modules keep their models in ``models.py``;
modules with business rules keep them in ``infrastructure/`` (AGENTS.md).
"""

import ast

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
