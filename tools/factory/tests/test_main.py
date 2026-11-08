from dataclasses import replace

from factory.config import Settings
from factory.diff import DiffStats, FileChange
from factory.main import Factory
from factory.runner import AgentResult
from factory.tickets import Ticket

OVERLAY = "Model: {{MODEL}}. Branch: {{BRANCH}}."

COMMAND_BODY = "Read .agents/skills/implement/SKILL.md and follow it.\n\n$ARGUMENTS"

DECISIONS_DOC = "# Summary\nBuilt the thing.\n\n# Decisions\n\n- Chose A.\n"


class FakeGit:
    def __init__(
        self,
        *,
        check_passed=True,
        check_output="",
        decisions="",
        diff=None,
        command_body=COMMAND_BODY,
    ):
        self.check_result = check_passed
        self.check_output = check_output
        self.decisions = decisions
        self.diff = diff or DiffStats()
        self.command_body = command_body
        self.committed = []
        self.pushed = []
        self.worktrees = []

    def create_worktree(self, repo_dir, worktree, branch):
        self.worktrees.append((branch, worktree))
        return worktree

    def write_file(self, worktree, relpath, content):
        return None

    def read_file(self, worktree, relpath):
        if relpath == "DECISIONS.md":
            return self.decisions
        if relpath == ".opencode/commands/implement.md":
            return self.command_body
        return ""

    def check(self, worktree):
        return (self.check_result, self.check_output)

    def commit_all(self, worktree, message):
        self.committed.append(message)
        return True

    def diff_stats(self, worktree):
        return self.diff

    def push(self, worktree, branch, token):
        self.pushed.append((branch, token))


class FakeGitHub:
    def __init__(self, tickets=None, pr_number=101):
        self.tickets = tickets or []
        self.pr_number = pr_number
        self.created_prs = []
        self.comments = []
        self.issue_labels = []
        self.pr_labels = []
        self.listed_with = None

    def list_tickets(self, token=None):
        self.listed_with = token
        return list(self.tickets)

    def create_draft_pr(self, *, branch, title, body, token):
        self.created_prs.append((branch, title, body, token))
        return self.pr_number

    def add_pr_label(self, number, label, token):
        self.pr_labels.append((number, label, token))

    def add_issue_label(self, number, label, token):
        self.issue_labels.append((number, label, token))

    def comment(self, number, body, token):
        self.comments.append((number, body, token))
        return f"https://github.com/r/issues/{number}#comment-1"


class FakeTokenProvider:
    def __init__(self, token="TOKEN"):
        self.token = token
        self.calls = []

    def mint(self, repo):
        self.calls.append(repo)
        return self.token


class FakeRunner:
    def __init__(self, result=None):
        self.result = result or AgentResult(exit_code=0, stdout="", stderr="", timed_out=False)
        self.calls = []

    def run(self, *, worktree, model, prompt, timeout_seconds):
        self.calls.append({"model": model, "prompt": prompt, "worktree": worktree})
        return self.result


class RecordingNotifier:
    def __init__(self):
        self.pr_ready = []
        self.stuck = []

    def send_pr_ready(self, info):
        self.pr_ready.append(info)

    def send_stuck(self, info):
        self.stuck.append(info)


def make_settings(tmp_path):
    return Settings(
        factory_model="deepseek/deepseek-flash",
        factory_strong_model="deepseek/deepseek-v4-pro",
        repo="daedraMex/commerce-platform",
        max_tickets=1,
        attempts=5,
        repo_dir=tmp_path / "repo",
        worktrees_dir=tmp_path / "worktrees",
        logs_dir=tmp_path / "logs",
        time_limit_seconds=60,
        keep_days=14,
        telegram_bot_token=None,
        telegram_chat_id=None,
        github_app_id="12345",
        github_private_key="fake-key",
        github_installation_id="67890",
    )


def make_ticket(number, *, labels=()):
    return Ticket(
        number=number,
        title=f"Ticket {number}",
        labels=frozenset(labels),
    )


def build_factory(tmp_path, *, git, github, runner, notifier, settings=None, token_provider=None):
    return Factory(
        settings or make_settings(tmp_path),
        github=github,
        git=git,
        runner=runner,
        notifier=notifier,
        token_provider=token_provider or FakeTokenProvider(),
        overlay=OVERLAY,
    )


def test_success_opens_draft_pr_and_notifies(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], pr_number=101)
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert len(github.created_prs) == 1
    branch, title, body, token = github.created_prs[0]
    assert branch == "nf/7-ticket-7"
    assert "Closes #7" in body
    assert "Built the thing." in body
    assert "Model: deepseek/deepseek-flash" in body
    assert "Chose A." in body
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]
    assert len(notifier.pr_ready) == 1


def test_success_labels_migration_when_migrations_changed(tmp_path):
    diff = DiffStats(
        files=(FileChange(path="backend/apps/orders/migrations/0002_x.py", added=1, deleted=0),),
        migrations_changed=True,
    )
    git = FakeGit(check_passed=True, diff=diff)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert github.pr_labels == [(101, "migration", "TOKEN")]


def test_protected_path_change_goes_stuck_without_push_or_pr(tmp_path):
    diff = DiffStats(
        files=(FileChange(path=".github/workflows/ci.yml", added=3, deleted=0),),
    )
    git = FakeGit(check_passed=True, diff=diff)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert github.created_prs == []
    assert notifier.stuck[0].failing_check == "protected path changed"


def test_failure_comments_and_labels_needs_decision(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert github.issue_labels == [(7, "needs-decision", "TOKEN")]
    assert len(github.comments) == 1
    assert len(notifier.stuck) == 1
    assert github.created_prs == []


def test_timeout_is_stuck(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner(AgentResult(exit_code=None, stdout="", stderr="", timed_out=True))
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert not results[0].ok
    assert notifier.stuck[0].failing_check == "time budget exceeded"


def test_open_question_is_stuck(tmp_path):
    git = FakeGit(check_passed=True, decisions="OPEN QUESTION: POST or PUT?\n\n- Chose X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert not results[0].ok
    assert notifier.stuck[0].open_question == "POST or PUT?"
    assert github.created_prs == []


def test_stops_at_first_failure(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(
        factory_model=settings.factory_model,
        factory_strong_model=settings.factory_strong_model,
        repo=settings.repo,
        max_tickets=2,
        attempts=settings.attempts,
        repo_dir=settings.repo_dir,
        worktrees_dir=settings.worktrees_dir,
        logs_dir=settings.logs_dir,
        time_limit_seconds=settings.time_limit_seconds,
        keep_days=settings.keep_days,
        telegram_bot_token=None,
        telegram_chat_id=None,
        github_app_id="12345",
        github_private_key="fake-key",
        github_installation_id="67890",
    )
    git = FakeGit(check_passed=False)
    github = FakeGitHub(
        tickets=[
            make_ticket(7, labels={"ready-for-agent"}),
            make_ticket(8, labels={"ready-for-agent"}),
        ]
    )
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
        settings=settings,
    )

    results = factory.run()

    assert [r.ticket.number for r in results] == [7]
    assert len(runner.calls) == 5


def test_strong_model_ticket_runs_with_strong_model(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent", "strong-model"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    assert runner.calls[0]["model"] == "deepseek/deepseek-v4-pro"
    assert "deepseek/deepseek-v4-pro" in runner.calls[0]["prompt"]


def test_success_mints_token_and_scopes_it_to_push_and_pr(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], pr_number=101)
    token_provider = FakeTokenProvider(token="MINTED-TOKEN")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
        token_provider=token_provider,
    )

    factory.run()

    assert token_provider.calls == [
        "daedraMex/commerce-platform",
        "daedraMex/commerce-platform",
    ]
    assert github.listed_with == "MINTED-TOKEN"
    assert git.pushed == [("nf/7-ticket-7", "MINTED-TOKEN")]
    assert github.created_prs[0][3] == "MINTED-TOKEN"


def test_stuck_mints_token_and_scopes_it_to_comment_and_label(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    token_provider = FakeTokenProvider(token="MINTED-TOKEN")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
        token_provider=token_provider,
    )

    factory.run()

    assert github.comments[0][2] == "MINTED-TOKEN"
    assert github.issue_labels[0][2] == "MINTED-TOKEN"


def test_step_budget_exhausted_sticks_and_notifies(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert not results[0].ok
    assert len(runner.calls) == 5
    assert notifier.stuck[0].failing_check == "step budget exceeded (5 attempts)"
    assert notifier.stuck[0].attempts == 5


def test_time_budget_exceeded_sticks_without_running(tmp_path):
    settings = replace(make_settings(tmp_path), time_limit_seconds=0)
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=notifier, settings=settings
    )

    results = factory.run()

    assert not results[0].ok
    assert len(runner.calls) == 0
    assert notifier.stuck[0].failing_check == "time budget exceeded"
    assert notifier.stuck[0].attempts == 0


def test_fix_loop_feeds_check_output_back_to_agent(tmp_path):
    git = FakeGit(check_passed=False, check_output="E   AssertionError")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    assert len(runner.calls) == 5
    assert "E   AssertionError" not in runner.calls[0]["prompt"]
    assert "E   AssertionError" in runner.calls[1]["prompt"]


def test_stuck_keeps_worktree_and_includes_handoff(tmp_path):
    settings = replace(make_settings(tmp_path), handoff_host="factory@host")
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier, settings=settings
    )

    factory.run()

    info = notifier.stuck[0]
    assert info.worktree.endswith("nf/7-ticket-7")
    assert info.handoff_command == f"ssh factory@host && cd {info.worktree}"
