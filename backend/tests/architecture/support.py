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
