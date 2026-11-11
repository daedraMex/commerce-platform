import ast
from pathlib import Path

import pytest

PHOTOS_DIR = Path(__file__).resolve().parents[3] / "apps" / "photos"
PURE_LAYERS = ("domain", "application")
FORBIDDEN_ROOTS = ("django", "rest_framework", "celery")


def imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def is_forbidden(name):
    if any(name == root or name.startswith(f"{root}.") for root in FORBIDDEN_ROOTS):
        return True
    parts = name.split(".")
    return len(parts) >= 3 and parts[0] == "apps" and parts[2] == "infrastructure"


@pytest.mark.parametrize("layer", PURE_LAYERS)
def test_pure_layers_import_no_framework_or_infrastructure(layer):
    sources = list((PHOTOS_DIR / layer).rglob("*.py"))
    offenders = [
        f"{path.relative_to(PHOTOS_DIR)} imports {name}"
        for path in sources
        for name in imported_modules(path)
        if is_forbidden(name)
    ]

    assert sources, f"the scan found no sources in {layer}/"
    assert offenders == []
