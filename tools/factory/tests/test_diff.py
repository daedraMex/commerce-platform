from factory.diff import (
    DiffStats,
    build_diff_stats,
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
    ]
    assert all(is_protected_path(path) for path in protected)


def test_is_protected_path_allows_normal_code():
    assert not is_protected_path("backend/apps/catalog/models.py")
    assert not is_protected_path("docs/adr/0026-something.md")
    assert not is_protected_path("web/storefront/package.json")


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
