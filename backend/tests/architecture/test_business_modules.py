"""Modules with business rules keep DRF thin: no ModelViewSet or ModelSerializer."""

import ast

from tests.architecture.support import APPS_DIR, business_modules, parse, relative, source_files

BANNED_BASES = {"ModelViewSet", "ModelSerializer", "HyperlinkedModelSerializer"}


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_business_modules_are_detected():
    assert "photos" in business_modules()


def test_business_modules_define_no_model_viewset_or_serializer():
    found = [
        f"{relative(path)}:{node.name}"
        for module in business_modules()
        for path in source_files(APPS_DIR / module)
        for node in ast.walk(parse(path))
        if isinstance(node, ast.ClassDef)
        and any(_base_name(base) in BANNED_BASES for base in node.bases)
    ]

    assert found == [], "Serializers validate shape and use cases enforce rules (AGENTS.md)."
