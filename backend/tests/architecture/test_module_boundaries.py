"""A module never imports another module's models; it goes through services or ports."""

import ast

from tests.architecture.support import APPS_DIR, parse, relative, source_files

# Foreign keys need the other module's model, and the Django admin wires inlines
# across modules (accounts registers the Store admin with its memberships).
ALLOWED_FILE_NAMES = {"models.py", "admin.py"}
# Existing violations, each tracked by an issue. Remove an entry when it is fixed.
EXCEPTIONS = {
    "apps/catalog/management/support.py": "#177",
    "apps/accounts/management/commands/e2e_seed.py": "#177",
}


def foreign_model_imports(path, own_module):
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if len(parts) >= 3 and parts[0] == "apps" and parts[2] == "models":
                if parts[1] != own_module:
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


def test_no_module_imports_another_modules_models():
    unexpected = {path: names for path, names in violations().items() if path not in EXCEPTIONS}

    assert unexpected == {}, (
        f"Use the other module's services or ports instead of its models: {unexpected}"
    )


def test_every_exception_is_still_a_violation():
    # A fixed exception must leave the list, so the guard covers that file again.
    assert set(EXCEPTIONS) <= set(violations())
