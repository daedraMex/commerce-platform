"""Shared helpers for the architecture tests: find source files and parse them."""

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
APPS_DIR = BACKEND_DIR / "apps"


def source_files(root=APPS_DIR):
    """Every Python file under ``root``, migrations excluded."""
    return sorted(path for path in root.rglob("*.py") if "migrations" not in path.parts)


def parse(path):
    return ast.parse(path.read_text(), filename=str(path))


def relative(path):
    return path.relative_to(BACKEND_DIR).as_posix()


def business_modules():
    """Modules with business rules follow clean architecture, so they have a domain/."""
    return sorted(
        path.name
        for path in APPS_DIR.iterdir()
        if (path / "domain").is_dir() and path.name != "shared"
    )


def import_aliases(tree):
    """Each local name an import binds, mapped to the dotted name it stands for.

    ``import a.b.c`` binds ``a``; ``import a.b as x`` binds ``x`` to ``a.b``;
    ``from a.b import c as d`` binds ``d`` to ``a.b.c``.
    """
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    head = alias.name.split(".", 1)[0]
                    aliases[head] = head
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def dotted(node):
    """``a.b.c`` for a Name/Attribute chain, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def resolved(node, aliases):
    """The full dotted name a Name/Attribute chain refers to through the imports."""
    name = dotted(node)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    base = aliases.get(head)
    if base is None:
        return None
    return f"{base}.{rest}" if rest else base
