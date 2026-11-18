import json
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

    def __init__(
        self,
        *,
        prs=None,
        pr_details=None,
        reviews=None,
        review_comments=None,
        issue=None,
    ):
        self.calls = []
        self.prs = prs
        self.pr_details = pr_details or {}
        self.reviews = reviews
        self.review_comments = review_comments or []
        self.issue = issue

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env))
        if argv[:3] == ["gh", "issue", "list"]:
            stdout = read_fixture("gh_issue_list.json")
        elif argv[:3] == ["gh", "issue", "view"]:
            fields = argv[argv.index("--json") + 1] if "--json" in argv else ""
            if fields == "state":
                stdout = read_fixture("gh_issue_view_open.json")
            elif self.issue is not None:
                stdout = json.dumps(self.issue)
            else:
                stdout = read_fixture("gh_issue_view_open.json")
        elif argv[:3] == ["gh", "pr", "list"]:
            fields = argv[argv.index("--json") + 1] if "--json" in argv else ""
            if self.prs is not None:
                stdout = json.dumps(self.prs)
            elif "author" in fields:
                stdout = read_fixture("gh_pr_list_open.json")
            else:
                stdout = read_fixture("gh_pr_list.json")
        elif argv[:3] == ["gh", "pr", "view"]:
            number = int(argv[3])
            detail = self.pr_details.get(number, {})
            stdout = json.dumps({"commits": detail.get("commits", [])})
        elif argv[:2] == ["gh", "api"]:
            endpoint = next((arg for arg in argv if arg.startswith("repos/")), "")
            if endpoint.endswith("/reviews"):
                if self.reviews is not None:
                    stdout = json.dumps(self.reviews)
                else:
                    number = int(endpoint.split("/pulls/")[1].split("/")[0])
                    reviews = self.pr_details.get(number, {}).get("reviews", [])
                    stdout = json.dumps(reviews)
            elif endpoint.endswith("/comments"):
                stdout = "\n".join(json.dumps(comment) for comment in self.review_comments)
            else:
                stdout = ""
        elif argv[:3] == ["gh", "pr", "create"]:
            stdout = read_fixture("gh_pr_create.txt")
        elif argv[:3] in (["gh", "pr", "ready"], ["gh", "pr", "merge"]):
            stdout = ""
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


def test_mark_pr_ready_marks_the_opened_pr():
    run = FakeGh()

    GitHub(REPO, run=run).mark_pr_ready(63, "TOKEN")

    assert run.calls[-1][0] == ["gh", "pr", "ready", "63", "--repo", REPO]
    assert run.calls[-1][2] == {"GH_TOKEN": "TOKEN"}


def test_mark_pr_ready_returns_the_failure_instead_of_raising():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="pull request is not a draft")

    result = GitHub(REPO, run=run).mark_pr_ready(63, "TOKEN")

    assert result.exit_code == 1
    assert result.stderr == "pull request is not a draft"


def test_enable_auto_merge_uses_the_merge_commit_method():
    run = FakeGh()

    result = GitHub(REPO, run=run).enable_auto_merge(63, "TOKEN")

    assert result.exit_code == 0
    assert run.calls[-1][0] == [
        "gh",
        "pr",
        "merge",
        "63",
        "--repo",
        REPO,
        "--auto",
        "--merge",
    ]
    assert run.calls[-1][2] == {"GH_TOKEN": "TOKEN"}


def test_enable_auto_merge_returns_the_failure_instead_of_raising():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr="Auto-merge is not allowed for this repository",
        )

    result = GitHub(REPO, run=run).enable_auto_merge(63, "TOKEN")

    assert result.exit_code == 1
    assert result.stderr == "Auto-merge is not allowed for this repository"


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


def _review(login, state, submitted_at, *, body="", review_id=5866656710):
    return {
        "id": review_id,
        "node_id": f"PRR_{review_id}",
        "user": {"login": login, "type": "User"},
        "state": state,
        "body": body,
        "submitted_at": submitted_at,
    }


def _commit(login, committed_at, *, name="xolo-bot[bot]"):
    return {
        "authoredDate": committed_at,
        "committedDate": committed_at,
        "authors": [{"login": login, "name": name}],
    }


def _pr(number, *, branch="nf/7-ticket-7", login="app/xolo-bot", body="Closes #7"):
    return {
        "number": number,
        "headRefName": branch,
        "author": {"login": login},
        "body": body,
    }


def _issue(number=7):
    return {
        "number": number,
        "title": f"Ticket {number}",
        "body": f"Body for #{number}",
        "labels": [{"name": "ready-for-agent"}],
    }


def test_list_review_fixes_picks_only_owner_changes_requested():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review(
                        "daedraMex",
                        "CHANGES_REQUESTED",
                        "2026-11-10T10:00:00Z",
                        body="Please fix this.",
                    )
                ],
                "commits": [_commit("xolo-bot[bot]", "2026-11-10T09:00:00Z")],
            }
        },
        review_comments=[
            {
                "path": "backend/apps/x/views.py",
                "line": 42,
                "original_line": 42,
                "body": "Rename this.",
            },
            {
                "path": "backend/apps/x/models.py",
                "line": None,
                "original_line": 9,
                "body": "This line moved.",
            },
        ],
        issue=_issue(7),
    )

    fixes = GitHub(REPO, run=run).list_review_fixes(
        author="xolo-bot", owner="daedraMex", token="TOKEN"
    )

    assert len(fixes) == 1
    fix = fixes[0]
    assert fix.pr_number == 101
    assert fix.branch == "nf/7-ticket-7"
    assert fix.ticket.number == 7
    assert fix.ticket.title == "Ticket 7"
    assert fix.review_body == "Please fix this."
    assert [(c.path, c.line, c.body) for c in fix.comments] == [
        ("backend/apps/x/views.py", 42, "Rename this."),
        ("backend/apps/x/models.py", 9, "This line moved."),
    ]
    assert "/reviews/5866656710/comments" in run.calls[-1][0][3]
    assert run.calls[-1][2] == {"GH_TOKEN": "TOKEN"}


def test_review_comments_use_the_numeric_id_from_the_recorded_rest_fixture():
    reviews = json.loads(read_fixture("gh_api_pr_reviews.json"))
    numeric_id = str(reviews[0]["id"])
    node_id = reviews[0]["node_id"]
    run = FakeGh(
        prs=[_pr(101)],
        reviews=reviews,
        pr_details={101: {"commits": []}},
        review_comments=[
            {
                "path": "backend/apps/x/views.py",
                "line": 42,
                "original_line": 42,
                "body": "Rename this.",
            }
        ],
        issue=_issue(7),
    )

    fixes = GitHub(REPO, run=run).list_review_fixes(
        author="xolo-bot", owner="daedraMex", token="TOKEN"
    )

    assert len(fixes) == 1
    assert fixes[0].review_id == numeric_id
    api_calls = [argv for argv, _cwd, _env in run.calls if argv[:2] == ["gh", "api"]]
    assert any(f"/reviews/{numeric_id}/comments" in arg for argv in api_calls for arg in argv)
    assert not any(node_id in arg for argv in api_calls for arg in argv)
    assert any(argv[3].endswith("/reviews") for argv in api_calls if len(argv) > 3)
    assert all(
        "--json" in argv and argv[argv.index("--json") + 1] == "commits"
        for argv, _cwd, _env in run.calls
        if argv[:3] == ["gh", "pr", "view"]
    )


def test_a_ledger_entry_with_a_node_id_does_not_block_the_numeric_review_id():
    run = FakeGh(
        prs=[_pr(101)],
        reviews=json.loads(read_fixture("gh_api_pr_reviews.json")),
        pr_details={101: {"commits": []}},
        review_comments=[],
        issue=_issue(7),
    )

    fixes = GitHub(REPO, run=run).list_review_fixes(
        author="xolo-bot",
        owner="daedraMex",
        attempted_review_ids=frozenset({"PRR_kwDOVUbRpc8AAAABXa4Txg"}),
    )

    assert len(fixes) == 1
    assert fixes[0].review_id == "5866656710"


def test_list_review_fixes_skips_an_approved_owner_review():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "APPROVED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [],
            }
        },
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_ignores_bot_reviews():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("app/xolo-bot", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [],
            }
        },
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_uses_the_latest_owner_review():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                    _review("daedraMex", "APPROVED", "2026-11-10T11:00:00Z"),
                ],
                "commits": [],
            }
        },
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_skips_when_a_factory_commit_landed_after_the_review():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [_commit("xolo-bot[bot]", "2026-11-10T10:30:00Z")],
            }
        },
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_accepts_a_commit_before_the_review():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [_commit("xolo-bot[bot]", "2026-11-10T09:00:00Z")],
            }
        },
        issue=_issue(7),
    )

    assert len(GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex")) == 1


def test_list_review_fixes_skips_when_an_owner_commit_landed_after_the_review():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [_commit("daedraMex", "2026-11-10T10:30:00Z", name="Erika Flores")],
            }
        },
        issue=_issue(7),
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_skips_an_already_attempted_review_id():
    run = FakeGh(
        prs=[_pr(101)],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [],
            }
        },
        issue=_issue(7),
    )

    fixes = GitHub(REPO, run=run).list_review_fixes(
        author="xolo-bot",
        owner="daedraMex",
        attempted_review_ids=frozenset({"5866656710"}),
    )

    assert fixes == []


def test_list_review_fixes_orders_by_oldest_review():
    run = FakeGh(
        prs=[
            _pr(102, branch="nf/9-ticket-9", body="Closes #9"),
            _pr(101, branch="nf/7-ticket-7", body="Closes #7"),
        ],
        pr_details={
            101: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T11:00:00Z"),
                ],
                "commits": [],
            },
            102: {
                "reviews": [
                    _review("daedraMex", "CHANGES_REQUESTED", "2026-11-10T10:00:00Z"),
                ],
                "commits": [],
            },
        },
        issue=_issue(7),
    )

    fixes = GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex")

    assert [fix.pr_number for fix in fixes] == [102, 101]


def test_list_review_fixes_ignores_prs_from_other_authors_or_branches():
    run = FakeGh(
        prs=[
            _pr(101, login="daedraMex"),
            _pr(102, branch="feat/human"),
        ],
    )

    assert GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex") == []


def test_list_review_fixes_raises_when_the_pr_list_fails():
    def run(_argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="network down")

    with pytest.raises(GitHubError, match="network down"):
        GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex")


def test_list_review_fixes_raises_when_the_review_view_fails():
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append(argv)
        if argv[:3] == ["gh", "pr", "list"]:
            return CommandResult(exit_code=0, stdout=json.dumps([_pr(101)]), stderr="")
        return CommandResult(exit_code=1, stdout="", stderr="review lookup failed")

    with pytest.raises(GitHubError, match="review lookup failed"):
        GitHub(REPO, run=run).list_review_fixes(author="xolo-bot", owner="daedraMex")


@pytest.mark.parametrize("separator", ["", "\n"])
def test_json_pages_flattens_concatenated_paginate_pages_in_order(separator):
    text = '[{"id": 1}, {"id": 2}]' + separator + '[{"id": 3}]\n'

    pages = GitHub(REPO)._json_pages(text, "gh api reviews")

    assert pages == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_json_pages_returns_an_empty_list_for_empty_output():
    assert GitHub(REPO)._json_pages("", "gh api reviews") == []
    assert GitHub(REPO)._json_pages("  \n", "gh api reviews") == []


def test_json_pages_raises_on_invalid_json():
    with pytest.raises(GitHubError, match="gh api reviews returned invalid JSON"):
        GitHub(REPO)._json_pages('[{"id": 1}][not json', "gh api reviews")


def test_json_pages_raises_when_a_page_is_not_a_list():
    with pytest.raises(GitHubError, match="gh api reviews returned an unexpected JSON shape"):
        GitHub(REPO)._json_pages('[{"id": 1}]{"message": "Not Found"}', "gh api reviews")


def test_has_open_pr_for_branch_lists_open_prs_by_head_branch():
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append(argv)
        return CommandResult(exit_code=0, stdout='[{"number": 12}]', stderr="")

    gh = GitHub("daedraMex/commerce-platform", run=run)

    assert gh.has_open_pr_for_branch("nf/7-x", "TOKEN") is True
    assert "--head" in calls[0] and "nf/7-x" in calls[0] and "open" in calls[0]


def test_has_open_pr_for_branch_is_false_without_open_prs():
    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=0, stdout="[]", stderr="")

    assert (
        GitHub("daedraMex/commerce-platform", run=run).has_open_pr_for_branch("nf/7-x", "TOKEN")
        is False
    )


def test_has_open_pr_for_branch_raises_when_gh_fails():
    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(exit_code=1, stdout="", stderr="HTTP 502")

    with pytest.raises(GitHubError, match="gh pr list failed: HTTP 502"):
        GitHub("daedraMex/commerce-platform", run=run).has_open_pr_for_branch("nf/7-x", "TOKEN")


class ScriptedGh:
    """Answer every gh call with one fixed result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        return self.result


@pytest.mark.parametrize("method", ["add_issue_label", "add_pr_label"])
def test_a_failed_label_write_raises(method):
    gh = ScriptedGh(CommandResult(1, "", "could not add label: 'needs-decision' not found"))

    with pytest.raises(GitHubError, match="needs-decision"):
        getattr(GitHub(REPO, run=gh), method)(95, "needs-decision", "tok")


@pytest.mark.parametrize("method", ["add_issue_label", "add_pr_label"])
def test_a_label_write_that_succeeds_returns_quietly(method):
    gh = ScriptedGh(CommandResult(0, "https://github.com/r/issues/95\n", ""))

    getattr(GitHub(REPO, run=gh), method)(95, "needs-decision", "tok")

    assert gh.calls[0][-2:] == ["--add-label", "needs-decision"]


def test_list_label_names_reads_every_name():
    gh = ScriptedGh(CommandResult(0, '[{"name":"needs-decision"},{"name":"migration"}]', ""))

    names = GitHub(REPO, run=gh).list_label_names("tok")

    assert names == frozenset({"needs-decision", "migration"})
    assert gh.calls[0][:3] == ["gh", "label", "list"]
    assert "--limit" in gh.calls[0]


def test_list_label_names_raises_when_gh_fails():
    gh = ScriptedGh(CommandResult(1, "", "HTTP 401"))

    with pytest.raises(GitHubError, match="HTTP 401"):
        GitHub(REPO, run=gh).list_label_names("tok")


class ContractGh:
    """Ready tickets, open PRs and issue bodies for the contract-hold tests (#144)."""

    def __init__(self, *, ready, prs, bodies, failing_issue=None):
        self.ready = ready
        self.prs = prs
        self.bodies = bodies
        self.failing_issue = failing_issue
        self.viewed = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        if argv[:3] == ["gh", "issue", "list"]:
            return CommandResult(0, json.dumps(self.ready), "")
        if argv[:3] == ["gh", "pr", "list"]:
            return CommandResult(0, json.dumps(self.prs), "")
        if argv[:3] == ["gh", "issue", "view"]:
            number = int(argv[3])
            fields = argv[argv.index("--json") + 1]
            if fields == "state":
                return CommandResult(0, '{"state":"CLOSED"}', "")
            self.viewed.append(number)
            if number == self.failing_issue:
                return CommandResult(1, "", "HTTP 502")
            return CommandResult(0, json.dumps({"body": self.bodies.get(number, "")}), "")
        return CommandResult(0, "[]", "")


CHANGES = "## Contracts\n\nChanges `photos.submission-states`.\n\n## Acceptance criteria\n"
CONSUMES = "## Contracts\n\nConsumes `photos.submission-states`.\n\n## Acceptance criteria\n"
CONSUMES_QUEUE = "## Contracts\n\nConsumes `photos.processing-queue`.\n"


def _ready(number, body):
    return {
        "number": number,
        "title": f"T{number}",
        "body": body,
        "labels": [{"name": "ready-for-agent"}],
    }


def test_a_ticket_whose_contract_an_open_pr_changes_carries_the_conflict():
    gh = ContractGh(
        ready=[_ready(170, CHANGES), _ready(100, CONSUMES), _ready(171, CONSUMES_QUEUE)],
        prs=[{"number": 175, "body": "Closes #156. Part of #79."}],
        bodies={156: CHANGES, 79: "Parent."},
    )

    tickets = {t.number: t for t in GitHub(REPO, run=gh).list_tickets("TOKEN")}

    assert tickets[170].contract_conflicts == ("photos.submission-states held by PR #175 (#156)",)
    assert tickets[100].contract_conflicts == ("photos.submission-states held by PR #175 (#156)",)
    assert tickets[171].contract_conflicts == ()


def test_two_consumers_never_conflict():
    gh = ContractGh(
        ready=[_ready(100, CONSUMES)],
        prs=[{"number": 175, "body": "Closes #134."}],
        bodies={134: CONSUMES},
    )

    (ticket,) = GitHub(REPO, run=gh).list_tickets("TOKEN")

    assert ticket.contract_conflicts == ()


def test_no_issue_body_is_read_when_no_ready_ticket_declares_contracts():
    gh = ContractGh(
        ready=[_ready(99, "## What to build\n\nA page.\n")],
        prs=[{"number": 175, "body": "Closes #156."}],
        bodies={156: CHANGES},
    )

    (ticket,) = GitHub(REPO, run=gh).list_tickets("TOKEN")

    assert ticket.contract_conflicts == ()
    assert gh.viewed == []


def test_an_unreadable_pr_ticket_fails_the_listing_instead_of_letting_tickets_race():
    gh = ContractGh(
        ready=[_ready(170, CHANGES)],
        prs=[{"number": 175, "body": "Closes #156."}],
        bodies={},
        failing_issue=156,
    )

    with pytest.raises(GitHubError, match="HTTP 502"):
        GitHub(REPO, run=gh).list_tickets("TOKEN")
