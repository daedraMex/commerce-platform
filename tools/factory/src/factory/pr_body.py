"""Pull request body.

Besides the summary and decisions, every body carries the evidence the owner
reads first: which checks passed, what deserves a full read, and how to undo
the merge.
"""

from __future__ import annotations

from .areas import Area
from .diff import DiffStats, is_sensitive_path


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
        "## Verification",
        "",
        *_verification(checked_areas, skipped_areas, steps_used, step_budget),
    ]
    if review_lines:
        parts += ["", "## Review", "", *review_lines]
    parts += ["", "## Risk", "", *_risk(diff)]
    parts += ["", "## How to revert", "", *_revert(diff)]
    return "\n".join(parts) + "\n"


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
