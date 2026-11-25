from dataclasses import dataclass

from factory.attempt_loop import DECISIONS_FILE, AttemptLoop, Feedback
from factory.git import CheckResult


@dataclass
class Result:
    timed_out: bool = False


class Runner:
    def __init__(self, decisions_by_step=None, timed_out_at=None, git=None):
        self.prompts = []
        self.decisions_by_step = decisions_by_step or {}
        self.timed_out_at = timed_out_at
        self.git = git

    def run(self, *, worktree, model, prompt, timeout_seconds, config_content):
        self.prompts.append(prompt)
        step = len(self.prompts)
        self.git.decisions = self.decisions_by_step.get(step, "- chose X")
        return Result(timed_out=step == self.timed_out_at)


class Git:
    def __init__(self, checks):
        self.checks = list(checks)
        self.decisions = ""

    def read_file(self, worktree, relpath):
        assert relpath == DECISIONS_FILE
        return self.decisions

    def check(self, worktree):
        return self.checks.pop(0)


class Review:
    def __init__(self, blocking_steps=(), stuck=None):
        self.blocking_steps = set(blocking_steps)
        self.stuck = stuck
        self.calls = []

    def __call__(self, step, previous, deadline):
        self.calls.append((step, previous))
        return FakeReview(step in self.blocking_steps, self.stuck, findings=(f"F{step}",))


@dataclass
class FakeReview:
    blocking: bool
    stuck: str | None
    findings: tuple = ()
    attack: object = None

    def stuck_check(self, *, last_step):
        return self.stuck


PASS = CheckResult(passed=True, output="ok")


def FAIL(text):
    return CheckResult(passed=False, output=text)


def _loop(git, runner, *, attempts=3, clock=None):
    return AttemptLoop(
        runner=runner,
        git=git,
        attempts=attempts,
        time_limit_seconds=100,
        clock=clock or (lambda: 0.0),
    )


def _run(loop, *, review=None, logged=None):
    return loop.run(
        worktree="/w",
        model="m",
        builder_config="{}",
        compose=lambda fb: f"check={fb.check_output}|review={fb.review}",
        write_log=lambda step, result: (logged if logged is not None else []).append(step),
        review=review,
    )


def test_without_a_review_green_checks_pass_and_failures_feed_the_next_prompt():
    git = Git([FAIL("E1"), PASS])
    runner = Runner(git=git)
    logged = []

    attempt = _run(_loop(git, runner), logged=logged)

    assert attempt.passed and attempt.attempts == 2 and attempt.check is PASS
    assert runner.prompts == ["check=|review=", "check=E1|review="]
    assert logged == [1, 2]


def test_a_blocking_review_feeds_its_findings_and_they_survive_a_failed_check(monkeypatch):
    monkeypatch.setattr(
        "factory.attempt_loop.build_reviewer_feedback",
        lambda findings, attack: "fix " + ",".join(findings),
    )
    git = Git([PASS, FAIL("E2"), PASS])
    runner = Runner(git=git)
    review = Review(blocking_steps={1})

    attempt = _run(_loop(git, runner), review=review)

    assert runner.prompts == ["check=|review=", "check=|review=fix F1", "check=E2|review=fix F1"]
    assert attempt.passed and attempt.previous_findings == ("F1",)
    assert review.calls == [(1, ()), (3, ("F1",))]


def test_a_review_that_stops_the_ticket_is_stuck():
    git = Git([PASS])

    attempt = _run(_loop(git, Runner(git=git)), review=Review(stuck="reviewer failed"))

    assert not attempt.passed and attempt.failing_check == "reviewer failed"


def test_an_open_question_stops_before_the_checks():
    git = Git([])
    runner = Runner(decisions_by_step={1: "OPEN QUESTION: POST or PUT?"}, git=git)

    attempt = _run(_loop(git, runner))

    assert attempt.failing_check == "decision needed"
    assert attempt.open_question == "POST or PUT?"
    assert attempt.attempts == 1


def test_an_agent_timeout_and_a_spent_deadline_are_the_time_budget():
    git = Git([])
    attempt = _run(_loop(git, Runner(timed_out_at=1, git=git)))
    assert attempt.failing_check == "time budget exceeded" and attempt.attempts == 1

    times = iter([0.0, 200.0])
    attempt = _run(_loop(Git([]), Runner(git=Git([])), clock=lambda: next(times)))
    assert attempt.failing_check == "time budget exceeded" and attempt.attempts == 0


def test_running_out_of_steps_names_the_budget():
    git = Git([FAIL("a"), FAIL("b")])

    attempt = _run(_loop(git, Runner(git=git), attempts=2))

    assert attempt.failing_check == "step budget exceeded (2 attempts)"
    assert attempt.decisions == "- chose X"


def test_feedback_defaults_are_empty():
    assert Feedback() == Feedback("", (), "")
