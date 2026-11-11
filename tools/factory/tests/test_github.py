from pathlib import Path

import pytest

from factory.github import GitHub, GitHubError, _same_login
from factory.shell import CommandResult

REPO = "daedraMex/commerce-platform"
FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeGh:
    """Answer the gh calls with outputs recorded from the real CLI."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env))
        if argv[:3] == ["gh", "issue", "list"]:
            stdout = read_fixture("gh_issue_list.json")
        elif argv[:3] == ["gh", "issue", "view"]:
            stdout = read_fixture("gh_issue_view_open.json")
        elif argv[:3] == ["gh", "pr", "list"]:
            fields = argv[argv.index("--json") + 1] if "--json" in argv else ""
            if "author" in fields:
                stdout = read_fixture("gh_pr_list_open.json")
            else:
                stdout = read_fixture("gh_pr_list.json")
        elif argv[:3] == ["gh", "pr", "create"]:
            stdout = read_fixture("gh_pr_create.txt")
        else:
            stdout = "{}"
        return CommandResult(exit_code=0, stdout=stdout, stderr="")


def test_list_tickets_uses_gh_token_for_every_read():
    run = FakeGh()
    GitHub(REPO, run=run).list_tickets("TOKEN")

    assert run.calls[0][0][:3] == ["gh", "issue", "list"]
    assert run.calls[1][0][:3] == ["gh", "pr", "list"]
    assert all(env == {"GH_TOKEN": "TOKEN"} for _argv, _cwd, env in run.calls)


def test_list_tickets_without_token_leaves_env_to_gh():
    run = FakeGh()
    GitHub(REPO, run=run).list_tickets()

    assert all(env is None for _argv, _cwd, env in run.calls)


def test_list_tickets_reads_label_names_from_recorded_label_objects():
    # `gh issue list --json labels` returns label objects, not strings.
    tickets = GitHub(REPO, run=FakeGh()).list_tickets("TOKEN")
    by_number = {ticket.number: ticket for ticket in tickets}

    assert by_number[50].title == "Phase 4 / 08: import_catalog --images"
    assert by_number[50].labels == frozenset({"ready-for-agent"})
    assert by_number[50].has_open_pr is False


def test_list_tickets_marks_a_ticket_closed_by_a_recorded_pr():
    tickets = GitHub(REPO, run=FakeGh()).list_tickets("TOKEN")
    by_number = {ticket.number: ticket for ticket in tickets}

    assert by_number[49].has_open_pr is True


def test_is_open_reads_recorded_state():
    run = FakeGh()

    assert GitHub(REPO, run=run)._is_open(21, "TOKEN") is True
    assert run.calls[-1][0] == ["gh", "issue", "view", "21", "--repo", REPO, "--json", "state"]


def test_is_open_fails_closed_when_gh_exits_nonzero():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="network down")

    assert GitHub(REPO, run=run)._is_open(21, "TOKEN") is True


def test_is_open_fails_closed_on_invalid_json():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=0, stdout="not json", stderr="")

    assert GitHub(REPO, run=run)._is_open(21, "TOKEN") is True


def test_create_draft_pr_reads_the_number_from_recorded_output():
    run = FakeGh()

    number = GitHub(REPO, run=run).create_draft_pr(
        branch="nf/7-test", title="#7: Test", body="Closes #7", token="TOKEN"
    )

    assert number == 63
    assert run.calls[-1][0][:3] == ["gh", "pr", "create"]
    assert run.calls[-1][2] == {"GH_TOKEN": "TOKEN"}


def test_count_open_factory_prs_filters_by_author_and_nf_prefix():
    run = FakeGh()

    count = GitHub(REPO, run=run).count_open_factory_prs(author="xolo-bot", token="TOKEN")

    # The captured fixture has one human PR on docs/* and two app/xolo-bot PRs on nf/*.
    assert count == 2
    assert run.calls[-1][0][:3] == ["gh", "pr", "list"]
    assert run.calls[-1][2] == {"GH_TOKEN": "TOKEN"}


@pytest.mark.parametrize(
    "login",
    ["app/xolo-bot", "xolo-bot", "xolo-bot[bot]", "app/xolo-bot[bot]"],
)
def test_bot_logins_with_app_prefix_or_bot_suffix_match(login):
    assert _same_login(login, "xolo-bot")


def test_count_open_factory_prs_raises_on_gh_error():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="network down")

    with pytest.raises(GitHubError, match="network down"):
        GitHub(REPO, run=run).count_open_factory_prs(author="xolo-bot")


def test_count_open_factory_prs_raises_on_invalid_json():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=0, stdout="not json", stderr="")

    with pytest.raises(GitHubError, match="invalid JSON"):
        GitHub(REPO, run=run).count_open_factory_prs(author="xolo-bot")


def test_open_pr_ticket_numbers_requests_a_high_limit():
    run = FakeGh()

    GitHub(REPO, run=run)._open_pr_ticket_numbers("TOKEN")

    argv = run.calls[-1][0]
    assert argv[argv.index("--limit") + 1] == "1000"


def test_open_pr_ticket_numbers_raises_on_gh_error():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="network down")

    with pytest.raises(GitHubError, match="network down"):
        GitHub(REPO, run=run)._open_pr_ticket_numbers("TOKEN")


def test_open_pr_ticket_numbers_raises_on_invalid_json():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=0, stdout="not json", stderr="")

    with pytest.raises(GitHubError, match="invalid JSON"):
        GitHub(REPO, run=run)._open_pr_ticket_numbers("TOKEN")
