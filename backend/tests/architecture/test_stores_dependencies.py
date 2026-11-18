import ast
from pathlib import Path

STORES_DIR = Path(__file__).resolve().parents[2] / "apps" / "stores"
# accounts depends on stores, so only this entry point may reach back into accounts.
ALLOWED = STORES_DIR / "management" / "commands" / "create_store.py"


def imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def imports_accounts(path):
    return any(
        name == "apps.accounts" or name.startswith("apps.accounts.")
        for name in imported_modules(path)
    )


def test_no_stores_module_but_create_store_imports_accounts():
    offenders = [
        str(path.relative_to(STORES_DIR))
        for path in STORES_DIR.rglob("*.py")
        if path != ALLOWED and imports_accounts(path)
    ]

    assert offenders == []


def test_the_scan_sees_the_allowed_import_in_create_store():
    # Guards the scan itself: if it found nothing anywhere, the test above would pass vacuously.
    assert imports_accounts(ALLOWED)
