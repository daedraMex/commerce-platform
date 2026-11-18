from factory.areas import BACKEND, CONSOLE
from factory.diff import DiffStats, FileChange
from factory.pr_body import build_pr_body


def test_pr_body_closes_ticket_and_records_model_and_decisions():
    body = _body(decisions="- Chose A over B because C.\n")
    assert "Closes #7" in body
    assert "Adds the widget endpoint." in body
    assert "Model: deepseek/deepseek-flash" in body
    assert "## Decisions" in body
    assert "Chose A over B because C." in body


def test_pr_body_omits_decisions_when_empty():
    body = _body(decisions="")
    assert "## Decisions" not in body
    assert "Closes #7" in body


def _body(**overrides):
    args = dict(
        ticket_number=7,
        summary="Adds the widget endpoint.",
        model="deepseek/deepseek-flash",
        decisions="",
        checked_areas=(BACKEND,),
        skipped_areas=(),
        diff=DiffStats(files=(FileChange("backend/apps/catalog/views.py", 3, 1),)),
        steps_used=2,
        step_budget=3,
    )
    args.update(overrides)
    return build_pr_body(**args)


def test_pr_body_lists_each_check_that_passed_and_the_steps_used():
    body = _body(checked_areas=(BACKEND, CONSOLE))

    assert "## Verification" in body
    assert "- `backend/scripts/check.sh` passed" in body
    assert "- `web/console/scripts/check.sh` passed" in body
    assert "Agent steps: 2 of 3" in body


def test_pr_body_says_when_no_check_script_ran():
    body = _body(checked_areas=(), skipped_areas=(BACKEND,))

    assert "No area check script ran" in body


def test_pr_body_flags_migrations_and_sensitive_paths_as_risk():
    diff = DiffStats(
        files=(
            FileChange("backend/apps/catalog/migrations/0009_x.py", 20, 0),
            FileChange("backend/apps/accounts/views.py", 4, 2),
        ),
        migrations_changed=True,
    )

    body = _body(diff=diff)

    assert "## Risk" in body
    assert "Migrations changed" in body
    assert "`backend/apps/accounts/views.py`" in body
    assert "None flagged" not in body


def test_pr_body_risk_says_none_flagged_for_ordinary_changes():
    body = _body()

    assert "## Risk" in body
    assert "None flagged" in body


def test_pr_body_explains_how_to_revert():
    plain = _body()
    with_migrations = _body(
        diff=DiffStats(
            files=(FileChange("backend/apps/catalog/migrations/0009_x.py", 20, 0),),
            migrations_changed=True,
        )
    )

    assert "## How to revert" in plain
    assert "Revert the merge commit" in plain
    assert "reverse migration" not in plain
    assert "reverse migration" in with_migrations


def test_pr_body_lists_areas_whose_script_was_missing():
    body = _body(checked_areas=(BACKEND,), skipped_areas=(CONSOLE,))

    assert "- `backend/scripts/check.sh` passed" in body
    assert "- `web/console/scripts/check.sh` skipped (script not found)" in body


def test_pr_body_flags_changed_dependencies_as_risk():
    diff = DiffStats(files=(FileChange("backend/uv.lock", 40, 2),))

    body = _body(diff=diff)

    assert "Dependencies changed" in body
    assert "`backend/uv.lock`" in body
