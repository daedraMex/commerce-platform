"""The steps of one ticket or review fix: agent, decisions, checks, review (#147).

New tickets and review fixes share this loop; they differ only in the prompt
they compose and whether a pre-PR review runs after green checks.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .areas import Area
from .decisions import extract_open_question
from .git import CheckResult
from .review_step import Finding, PrePrReview, build_reviewer_feedback, stuck_reason

DECISIONS_FILE = "DECISIONS.md"
TIME_BUDGET_EXCEEDED = "time budget exceeded"


@dataclass(frozen=True)
class Feedback:
    """What the next prompt carries from the previous step."""

    check_output: str = ""
    failed_areas: tuple[Area, ...] = ()
    review: str = ""


@dataclass(frozen=True)
class Attempt:
    """How the loop ended: checks passed (and the review let it through), or stuck."""

    attempts: int
    decisions: str
    failing_check: str | None = None
    open_question: str | None = None
    check: CheckResult | None = None
    review: PrePrReview | None = None
    previous_findings: tuple[Finding, ...] = ()

    @property
    def passed(self) -> bool:
        return self.failing_check is None


ComposePrompt = Callable[[Feedback], str]
WriteLog = Callable[[int, object], None]
LogCheck = Callable[[int, CheckResult], None]
Review = Callable[[int, tuple[Finding, ...], float], PrePrReview]


class AttemptLoop:
    def __init__(
        self,
        *,
        runner,
        git,
        attempts: int,
        time_limit_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.runner = runner
        self.git = git
        self.attempts = attempts
        self.time_limit_seconds = time_limit_seconds
        self._clock = clock

    def run(
        self,
        *,
        worktree: Path,
        model: str,
        builder_config: str,
        compose: ComposePrompt,
        write_log: WriteLog,
        review: Review | None = None,
        log_check: LogCheck | None = None,
    ) -> Attempt:
        """Run up to ``attempts`` steps before the deadline.

        Each step runs the agent, reads its decisions (an open question stops the
        loop), then the checks. Failed checks feed the next prompt. With
        ``review``, green checks go through the pre-PR review: blocking findings
        feed the next prompt, and only a review that lets the change through
        passes the loop.
        """
        deadline = self._clock() + self.time_limit_seconds
        made = 0
        decisions = ""
        feedback = Feedback()
        previous: tuple[Finding, ...] = ()
        for step in range(1, self.attempts + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                return Attempt(made, decisions, failing_check=TIME_BUDGET_EXCEEDED)
            result = self.runner.run(
                worktree=worktree,
                model=model,
                prompt=compose(feedback),
                timeout_seconds=int(remaining),
                config_content=builder_config,
            )
            made += 1
            write_log(step, result)
            decisions = self.git.read_file(worktree, DECISIONS_FILE)
            open_question = extract_open_question(decisions)
            if open_question:
                return Attempt(
                    made, decisions, failing_check="decision needed", open_question=open_question
                )
            if result.timed_out:
                return Attempt(made, decisions, failing_check=TIME_BUDGET_EXCEEDED)
            check = self.git.check(worktree)
            if log_check is not None:
                log_check(step, check)
            if not check.passed:
                # The open review findings stay in the next prompt until a review passes.
                feedback = Feedback(check.output, check.failed_areas, feedback.review)
                continue
            if review is None:
                return Attempt(made, decisions, check=check)
            outcome = review(step, previous, deadline)
            stuck_check = outcome.stuck_check(last_step=step >= self.attempts)
            if stuck_check is not None:
                return Attempt(made, decisions, failing_check=stuck_check)
            if outcome.blocking:
                feedback = Feedback(
                    review=build_reviewer_feedback(outcome.findings, outcome.attack)
                )
                previous = outcome.findings
                continue
            return Attempt(made, decisions, check=check, review=outcome, previous_findings=previous)
        open_findings = [f for f in previous if f.tag == "Important"]
        return Attempt(
            made,
            decisions,
            failing_check=(
                f"check failed; {stuck_reason(open_findings[0])}"
                if open_findings
                else f"step budget exceeded ({self.attempts} attempts)"
            ),
        )
