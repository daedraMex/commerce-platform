from factory.diff import (
    DiffStats,
    build_diff_stats,
    is_dependency_path,
    is_migration_path,
    is_protected_path,
    is_sensitive_path,
    is_test_path,
    touches_protected_paths,
)


def test_build_diff_stats_sums_added_and_deleted():
    numstat = (
        "10\t2\tbackend/apps/orders/use_cases/place_order.py\n0\t5\tbackend/apps/orders/models.py\n"
    )
    stats = build_diff_stats(numstat, new_files=[])
    assert stats.added == 10
    assert stats.deleted == 7
    assert [f.path for f in stats.files] == [
        "backend/apps/orders/use_cases/place_order.py",
        "backend/apps/orders/models.py",
    ]


def test_build_diff_stats_handles_binary():
    stats = build_diff_stats("-\t-\tweb/public/image.png\n", new_files=[])
    assert stats.files[0].added == 0
    assert stats.files[0].deleted == 0


def test_build_diff_stats_detects_new_tests():
    numstat = "12\t0\tbackend/tests/unit/test_place_order.py\n"
    stats = build_diff_stats(numstat, new_files=["backend/tests/unit/test_place_order.py"])
    assert stats.new_tests == ("backend/tests/unit/test_place_order.py",)


def test_build_diff_stats_detects_migrations():
    numstat = "1\t0\tbackend/apps/orders/migrations/0002_x.py\n"
    stats = build_diff_stats(numstat, new_files=[])
    assert stats.migrations_changed is True


def test_is_migration_path():
    assert is_migration_path("backend/apps/orders/migrations/0002_x.py")
    assert not is_migration_path("backend/apps/orders/models.py")


def test_is_test_path():
    assert is_test_path("backend/tests/unit/test_x.py")
    assert not is_test_path("backend/apps/orders/models.py")


def test_empty_stats():
    stats = DiffStats()
    assert stats.added == 0
    assert stats.deleted == 0


def test_is_protected_path_covers_the_guarded_files_and_dirs():
    protected = [
        ".github/workflows/ci.yml",
        "tools/factory/src/factory/main.py",
        "backend/scripts/check.sh",
        ".opencode/commands/implement.md",
        "AGENTS.md",
        "CLAUDE.md",
        "REVIEW.md",
        ".pre-commit-config.yaml",
        "opencode.json",
        "opencode.factory.json",
        "web/opencode.json",
        "web/console/scripts/check.sh",
        "backend/tests/conftest.py",
        "backend/tests/integration/conftest.py",
    ]
    assert all(is_protected_path(path) for path in protected)


def test_is_protected_path_allows_normal_code():
    assert not is_protected_path("backend/apps/catalog/models.py")
    assert not is_protected_path("docs/adr/0026-something.md")
    assert not is_protected_path("web/console/src/app/page.tsx")


def test_touches_protected_paths_ignores_nothing_normal():
    assert touches_protected_paths(["backend/apps/catalog/models.py"]) is False
    assert touches_protected_paths(["backend/apps/catalog/models.py", "AGENTS.md"]) is True


def test_is_sensitive_path_covers_auth_permissions_and_settings():
    sensitive = [
        "backend/apps/accounts/views.py",
        "backend/apps/stores/authorizer.py",
        "backend/config/settings.py",
        "backend/config/urls.py",
        "backend/apps/shared/domain/ports.py",
        "web/console/src/lib/auth/session.ts",
    ]
    assert all(is_sensitive_path(path) for path in sensitive)


def test_is_sensitive_path_allows_ordinary_code():
    assert not is_sensitive_path("backend/apps/catalog/views.py")
    assert not is_sensitive_path("web/console/src/app/[store]/photos/page.tsx")


def test_every_opencode_config_form_is_protected():
    assert is_protected_path("opencode.jsonc")
    assert is_protected_path("web/console/opencode.jsonc")


DEPENDENCY_PATHS = [
    "package.json",
    "pnpm-lock.yaml",
    "web/console/package.json",
    "packages/api-client/package.json",
    "backend/pyproject.toml",
    "backend/uv.lock",
]


def test_dependency_files_are_protected_unless_the_ticket_allows_them():
    assert all(is_protected_path(path) for path in DEPENDENCY_PATHS)
    assert not any(is_protected_path(path, allow_dependencies=True) for path in DEPENDENCY_PATHS)
    assert all(is_dependency_path(path) for path in DEPENDENCY_PATHS)


def test_deps_change_never_unlocks_conftest_or_the_factory():
    for path in ("backend/tests/conftest.py", "tools/factory/uv.lock", "AGENTS.md"):
        assert is_protected_path(path, allow_dependencies=True)


def test_touches_protected_paths_passes_the_dependency_allowance():
    paths = ["backend/apps/x.py", "backend/uv.lock"]
    assert touches_protected_paths(paths) is True
    assert touches_protected_paths(paths, allow_dependencies=True) is False


def test_opencode_edit_denies_match_the_protected_lists():
    import json
    from pathlib import Path

    from factory.diff import PROTECTED_FILES, PROTECTED_NAMES, PROTECTED_PREFIXES

    config = json.loads((Path(__file__).resolve().parents[1] / "opencode.factory.json").read_text())
    edit = config["permission"]["edit"]
    expected = (
        set(PROTECTED_FILES)
        | {f"{prefix}*" for prefix in PROTECTED_PREFIXES}
        | {f"*{name}" for name in PROTECTED_NAMES}
        | {"*opencode*.json", "*opencode*.jsonc"}
    )
    # Denies the guard does not mirror on purpose: env files and ADRs.
    deny_only = {"*.env", "*.env.*", "docs/adr/*"}
    denied = {pattern for pattern, rule in edit.items() if rule == "deny"}
    assert denied - deny_only == expected


def test_a_lockfile_change_is_always_dependency_only():
    from factory.diff import non_dependency_change

    assert non_dependency_change("backend/uv.lock", "a", "b") is None


def test_package_json_may_change_only_its_dependency_sections():
    from factory.diff import non_dependency_change

    old = '{"name": "c", "scripts": {"lint": "eslint ."}, "dependencies": {"a": "1"}}'
    deps = '{"name": "c", "scripts": {"lint": "eslint ."}, "dependencies": {"a": "2", "b": "1"}}'
    scripts = '{"name": "c", "scripts": {"lint": "true"}, "dependencies": {"a": "1"}}'

    assert non_dependency_change("web/console/package.json", old, deps) is None
    reason = non_dependency_change("web/console/package.json", old, scripts)
    assert "scripts" in reason


def test_pyproject_may_change_only_its_dependency_tables():
    from factory.diff import non_dependency_change

    def pyproject(dependencies, addopts):
        return (
            f'[project]\nname = "b"\ndependencies = {dependencies}\n\n'
            f'[tool.pytest.ini_options]\naddopts = "{addopts}"\n'
        )

    old = pyproject('["django"]', "")
    deps = pyproject('["django", "hypothesis"]', "")
    tool = pyproject('["django"]', "--collect-only")

    assert non_dependency_change("backend/pyproject.toml", old, deps) is None
    assert "tool" in non_dependency_change("backend/pyproject.toml", old, tool)


def test_a_new_or_unreadable_dependency_manifest_is_not_dependency_only():
    from factory.diff import non_dependency_change

    assert non_dependency_change("web/new/package.json", None, "{}") is not None
    assert non_dependency_change("web/console/package.json", "{}", "{not json") is not None
