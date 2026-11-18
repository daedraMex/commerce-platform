"""Store actions are authorized through the Authorizer port, never user.has_perm()."""

import ast

from tests.architecture.support import parse, relative, source_files

# Django's permissions only gate the admin.
ALLOWED_FILE_NAMES = {"admin.py"}
BANNED_CALLS = {"has_perm", "has_perms"}


def test_no_has_perm_outside_the_admin():
    calls = [
        f"{relative(path)}:{node.lineno}"
        for path in source_files()
        if path.name not in ALLOWED_FILE_NAMES
        for node in ast.walk(parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in BANNED_CALLS
    ]

    assert calls == [], "Authorize store actions with the Authorizer port, not has_perm()."
