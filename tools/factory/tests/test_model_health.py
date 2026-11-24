from factory.model_health import (
    MODEL_CHECK_MAX_AGE_SECONDS,
    ModelChecks,
    ReviewerFailures,
)


def test_a_model_never_checked_is_due(tmp_path):
    assert ModelChecks(tmp_path / "state", clock=lambda: 1000).due("anthropic/claude-sonnet-5-5")


def test_a_model_checked_within_a_day_is_not_due_and_another_still_is(tmp_path):
    now = [1000.0]
    checks = ModelChecks(tmp_path / "state", clock=lambda: now[0])

    checks.passed("anthropic/claude-sonnet-5-5")
    now[0] += MODEL_CHECK_MAX_AGE_SECONDS - 1

    assert not checks.due("anthropic/claude-sonnet-5-5")
    assert checks.due("deepseek/deepseek-flash")


def test_a_model_checked_a_day_ago_is_due_again(tmp_path):
    now = [1000.0]
    checks = ModelChecks(tmp_path / "state", clock=lambda: now[0])
    checks.passed("deepseek/deepseek-flash")

    now[0] += MODEL_CHECK_MAX_AGE_SECONDS

    assert ModelChecks(tmp_path / "state", clock=lambda: now[0]).due("deepseek/deepseek-flash")


def test_a_corrupt_model_checks_file_makes_every_model_due(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "model-checks.json").write_text("{not json")

    assert ModelChecks(state, clock=lambda: 1000).due("deepseek/deepseek-flash")


def test_reviewer_failures_count_in_a_row_and_a_success_resets_them(tmp_path):
    failures = ReviewerFailures(tmp_path / "state")

    assert failures.failed() == 1
    assert ReviewerFailures(tmp_path / "state").failed() == 2
    failures.succeeded()

    assert failures.failed() == 1


def test_state_files_are_private(tmp_path):
    state = tmp_path / "state"
    ModelChecks(state, clock=lambda: 1000).passed("m")
    ReviewerFailures(state).failed()

    assert oct(state.stat().st_mode & 0o777) == "0o700"
    for name in ("model-checks.json", "reviewer-failures.json"):
        assert oct((state / name).stat().st_mode & 0o777) == "0o600"
