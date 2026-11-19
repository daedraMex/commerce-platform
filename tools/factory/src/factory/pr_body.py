"""Pull request body.

Besides the summary and decisions, every body carries the evidence the owner
reads first: which checks passed, what deserves a full read, and how to undo
the merge.
"""

from __future__ import annotations

import re

from .areas import Area
from .diff import DiffStats, is_check_config_path, is_dependency_path, is_sensitive_path

# The Verification section names the exact commit its checks ran on. The
# "Evidence" job in .github/workflows/pr-ticket.yml fails a factory PR whose head
# is not that commit, so a push after the checks cannot merge on old evidence.
VERIFICATION_BEGIN = "<!-- factory:verification sha={sha} -->"
VERIFICATION_END = "<!-- /factory:verification -->"
_VERIFICATION_RE = re.compile(
    r"<!-- factory:verification sha=[0-9a-f]{40} -->.*?<!-- /factory:verification -->",
    re.DOTALL,
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CHECK_TAIL_LINES = 15
FENCE = "`" * 3


def build_pr_body(
    *,
    ticket_number: int,
    summary: str,
    model: str,
    decisions: str,
    checked_areas: tuple[Area, ...],
    skipped_areas: tuple[Area, ...],
    diff: DiffStats,
    review_lines: tuple[str, ...] = (),
    steps_used: int,
    step_budget: int,
    verified_sha: str,
    check_output: str = "",
) -> str:
    parts: list[str] = [
        f"Closes #{ticket_number}",
        "",
        "## Summary",
        "",
        summary.strip(),
    ]
    if model:
        parts += ["", f"Model: {model}"]
    if decisions.strip():
        parts += ["", "## Decisions", "", decisions.strip()]
    parts += [
        "",
        verification_section(
            verified_sha=verified_sha,
            checked_areas=checked_areas,
            skipped_areas=skipped_areas,
            steps_used=steps_used,
            step_budget=step_budget,
            check_output=check_output,
        ),
    ]
    if review_lines:
        parts += ["", "## Review", "", *review_lines]
    parts += ["", "## Risk", "", *_risk(diff)]
    parts += ["", "## How to revert", "", *_revert(diff)]
    return "\n".join(parts) + "\n"


def verification_section(
    *,
    verified_sha: str,
    checked_areas: tuple[Area, ...],
    skipped_areas: tuple[Area, ...],
    steps_used: int,
    step_budget: int,
    check_output: str = "",
) -> str:
    """The Verification section, wrapped in markers that name the checked commit."""
    if not _SHA_RE.match(verified_sha):
        # Fail closed: without a full sha the Evidence check could never pass, so
        # refuse to build a body that would only fail later with a vaguer message.
        raise ValueError(f"verified_sha must be a full 40-char sha, got {verified_sha!r}")
    lines = [
        VERIFICATION_BEGIN.format(sha=verified_sha),
        "## Verification",
        "",
        f"Checks ran on commit `{verified_sha}`.",
        "",
        *_verification(checked_areas, skipped_areas, steps_used, step_budget),
    ]
    tail = _tail(check_output)
    if tail:
        lines += [
            "",
            "<details><summary>Last lines of the check output</summary>",
            "",
            FENCE,
            tail,
            FENCE,
            "",
            "</details>",
        ]
    lines.append(VERIFICATION_END)
    return "\n".join(lines)


def replace_verification(body: str, section: str) -> str:
    """Swap the Verification section of an existing PR body for a new one.

    A body from before the markers existed gets the section appended, so the
    Evidence check can pass after a review fix without a human editing it.
    """
    if _VERIFICATION_RE.search(body):
        return _VERIFICATION_RE.sub(lambda _: section, body, count=1)
    return body.rstrip("\n") + "\n\n" + section + "\n"


def _tail(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    # A fence inside the output would close the code block early.
    return "\n".join(line.replace(FENCE, "'''") for line in lines[-CHECK_TAIL_LINES:])


def _verification(
    checked_areas: tuple[Area, ...],
    skipped_areas: tuple[Area, ...],
    steps_used: int,
    step_budget: int,
) -> list[str]:
    lines = [f"- `{area.script.as_posix()}` passed" for area in checked_areas]
    if not lines:
        lines = ["- No area check script ran."]
    lines += [f"- `{area.script.as_posix()}` skipped (script not found)" for area in skipped_areas]
    return [*lines, f"- Agent steps: {steps_used} of {step_budget}"]


def _risk(diff: DiffStats) -> list[str]:
    lines: list[str] = []
    if diff.migrations_changed:
        lines.append("- Migrations changed: review them before merging.")
    dependencies = [f.path for f in diff.files if is_dependency_path(f.path)]
    if dependencies:
        lines.append("- Dependencies changed (deps-change ticket):")
        lines += [f"  - `{path}`" for path in dependencies]
    check_config = [f.path for f in diff.files if is_check_config_path(f.path)]
    if check_config:
        lines.append("- Check configuration changed (read in full: it decides what checks see):")
        lines += [f"  - `{path}`" for path in check_config]
    sensitive = [f.path for f in diff.files if is_sensitive_path(f.path)]
    if sensitive:
        lines.append("- Sensitive paths (read in full):")
        lines += [f"  - `{path}`" for path in sensitive]
    return lines or ["- None flagged."]


def _revert(diff: DiffStats) -> list[str]:
    lines = ["- Revert the merge commit."]
    if diff.migrations_changed:
        lines.append(
            "- This PR changes migrations: run the reverse migration "
            "(`migrate <app> <previous>`) before reverting the code."
        )
    return lines
