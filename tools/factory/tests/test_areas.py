from pathlib import Path

from factory.areas import AREAS, BACKEND, CONSOLE, area_for_path, select_areas


def test_backend_path_selects_only_the_backend_area():
    assert select_areas(["backend/apps/catalog/views.py"]) == (BACKEND,)


def test_console_path_selects_only_the_console_area():
    assert select_areas(["web/console/app/page.tsx"]) == (CONSOLE,)


def test_packages_path_selects_the_console_area():
    assert select_areas(["packages/api-client/src/index.ts"]) == (CONSOLE,)


def test_backend_ticket_refreshing_openapi_runs_both_areas():
    paths = [
        "backend/apps/catalog/views.py",
        "packages/api-client/openapi.json",
    ]

    assert select_areas(paths) == (BACKEND, CONSOLE)


def test_docs_only_ticket_runs_every_area():
    assert select_areas(["docs/factory.md", "AGENTS.md"]) == AREAS


def test_no_paths_runs_every_area():
    assert select_areas([]) == AREAS


def test_area_for_path_ignores_unrelated_files():
    assert area_for_path("docs/factory.md") is None
    assert area_for_path("web/storefront/page.tsx") is None


def test_area_scripts_are_relative_to_the_worktree_root():
    assert BACKEND.script == Path("backend") / "scripts" / "check.sh"
    assert CONSOLE.script == Path("web") / "console" / "scripts" / "check.sh"
