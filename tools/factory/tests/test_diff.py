from factory.diff import DiffStats, build_diff_stats, is_migration_path, is_test_path


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
