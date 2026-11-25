"""Other modules reach the catalog only through its interface (ADR-0005, amended).

The interface is ``apps.catalog.services`` (commands and records), ``apps.catalog.rules``
(pure rules) and the public URL builders ``media_url`` and ``rendition_url`` from
``apps.catalog.media``. The composition root in ``config/`` may wire the catalog's
repositories; it is not under ``apps/``.
"""

import ast

from tests.architecture.support import (
    APPS_DIR,
    import_aliases,
    parse,
    relative,
    resolved,
    source_files,
)

CATALOG = "apps.catalog"
INTERFACE_MODULES = {f"{CATALOG}.services", f"{CATALOG}.rules"}
MEDIA_MODULE = f"{CATALOG}.media"
MEDIA_NAMES = {"media_url", "rendition_url"}


def _allowed(name):
    """Whether a dotted name inside ``apps.catalog`` is part of its interface."""
    if name == CATALOG:
        return True
    if any(name == module or name.startswith(f"{module}.") for module in INTERFACE_MODULES):
        return True
    return name in {f"{MEDIA_MODULE}.{media}" for media in MEDIA_NAMES}


def catalog_interface_violations(tree):
    """(line, dotted name) for each reference to the catalog outside its interface."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == CATALOG or node.module.startswith(f"{CATALOG}."):
                for alias in node.names:
                    name = f"{node.module}.{alias.name}"
                    if not _allowed(name):
                        found.append((node.lineno, name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith(f"{CATALOG}.") and not _allowed(name):
                    found.append((node.lineno, name))
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = resolved(node, aliases)
            if name and name.startswith(f"{CATALOG}.") and not _allowed(name):
                # Report the outermost chain only once per line.
                if (node.lineno, name) not in found and not any(
                    line == node.lineno and other.startswith(name) for line, other in found
                ):
                    found.append((node.lineno, name))
    return sorted(set(found))


def _outside_catalog():
    catalog_dir = APPS_DIR / "catalog"
    return [path for path in source_files() if catalog_dir not in path.parents]


def test_other_modules_use_only_the_catalog_interface():
    violations = [
        f"{relative(path)}:{line} {name}"
        for path in _outside_catalog()
        for line, name in catalog_interface_violations(parse(path))
    ]

    assert violations == [], (
        "Use apps.catalog.services, apps.catalog.rules or the media URL builders (ADR-0005)."
    )


def test_the_guard_catches_every_way_around_the_interface():
    tree = ast.parse(
        "from apps.catalog.models import Product\n"
        "from apps.catalog import repositories\n"
        "from apps.catalog.media import media_url, store_media\n"
        "import apps.catalog.views\n"
        "import apps.catalog.services\n"
        "apps.catalog.models.Product\n"
    )

    assert catalog_interface_violations(tree) == [
        (1, "apps.catalog.models.Product"),
        (2, "apps.catalog.repositories"),
        (3, "apps.catalog.media.store_media"),
        (4, "apps.catalog.views"),
        (6, "apps.catalog.models.Product"),
    ]


def test_the_guard_allows_the_interface():
    tree = ast.parse(
        "from apps.catalog.services import MediaRecord, StoreMismatch\n"
        "from apps.catalog import services, rules\n"
        "from apps.catalog.rules import slugify\n"
        "from apps.catalog.media import media_url, rendition_url\n"
        "import apps.catalog.services as catalog_services\n"
        "catalog_services.CatalogService\n"
    )

    assert catalog_interface_violations(tree) == []
