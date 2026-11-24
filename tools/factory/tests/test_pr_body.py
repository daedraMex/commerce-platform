import pytest

from factory.areas import BACKEND, CONSOLE
from factory.diff import DiffStats, FileChange
from factory.pr_body import build_pr_body, replace_verification, verification_section


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


SHA = "c" * 40
NEW_SHA = "d" * 40


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
        verified_sha=SHA,
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


def test_pr_body_flags_check_configuration_as_risk():
    diff = DiffStats(
        files=(
            FileChange("web/console/vitest.config.mts", 1, 1),
            FileChange("web/console/src/app/page.tsx", 3, 0),
        ),
    )

    body = _body(diff=diff)

    risk = body.split("## Risk", 1)[1].split("## How to revert", 1)[0]
    assert "Check configuration changed" in risk
    assert "`web/console/vitest.config.mts`" in risk
    assert "page.tsx" not in risk


def test_pr_body_ties_the_verification_to_the_checked_commit():
    body = _body()

    assert f"<!-- factory:verification sha={SHA} -->" in body
    assert f"Checks ran on commit `{SHA}`." in body
    assert "<!-- /factory:verification -->" in body


def test_pr_body_refuses_a_short_or_missing_sha():
    with pytest.raises(ValueError):
        _body(verified_sha="abc1234")
    with pytest.raises(ValueError):
        _body(verified_sha="")


def test_pr_body_shows_the_tail_of_the_check_output_without_breaking_the_fence():
    output = "\n".join(f"line {i}" for i in range(40)) + "\n```oops```"

    body = _body(check_output=output)

    assert "Last lines of the check output" in body
    assert "line 39" in body
    assert "line 10" not in body
    assert "```oops```" not in body


def test_pr_body_without_check_output_has_no_details_block():
    assert "<details>" not in _body(check_output="")


def _section(sha):
    return verification_section(
        verified_sha=sha,
        checked_areas=(BACKEND,),
        skipped_areas=(),
        steps_used=1,
        step_budget=3,
    )


def test_replace_verification_swaps_only_the_marked_section():
    body = _body(decisions="- Kept A.\n")

    updated = replace_verification(body, _section(NEW_SHA))

    assert f"sha={NEW_SHA}" in updated
    assert f"sha={SHA}" not in updated
    assert updated.count("## Verification") == 1
    assert "Kept A." in updated
    assert "## How to revert" in updated


def test_replace_verification_appends_to_a_body_without_markers():
    updated = replace_verification("Closes #7\n\n## Summary\n\nOld PR.\n", _section(NEW_SHA))

    assert updated.startswith("Closes #7")
    assert f"sha={NEW_SHA}" in updated


def test_pr_body_risk_lists_contracts_the_ticket_did_not_declare_as_changed():
    """#134 declared photos.catalog-port as consumed; PR #195 changed it (#203)."""
    body = _body(
        undeclared_contracts=(
            ("photos.catalog-port", "declared as consumed"),
            ("photos.processing-queue", "not declared"),
        )
    )

    risk = body.split("## Risk", 1)[1].split("## How to revert", 1)[0]
    assert "Contracts changed that the ticket does not declare as changed" in risk
    assert "`photos.catalog-port`: declared as consumed" in risk
    assert "`photos.processing-queue`: not declared" in risk
    assert "None flagged" not in risk


def test_pr_body_risk_is_unchanged_when_every_changed_contract_is_declared():
    assert _body(undeclared_contracts=()) == _body()
