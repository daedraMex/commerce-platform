import pytest

from factory.diff import DiffStats, FileChange
from factory.publisher import Publisher
from factory.tickets import Ticket

TICKET = Ticket(number=7, title="Ticket 7")


class Git:
    def __init__(self, files=(), files_by_ref=None, files_now=None):
        self.diff = DiffStats(files=tuple(FileChange(p, 1, 0) for p in files))
        self.calls = []
        self.files_by_ref = files_by_ref or {}
        self.files_now = files_now or {}

    def commit_all(self, worktree, message):
        self.calls.append(("commit_all", message))

    def diff_stats(self, worktree, *, since=None):
        self.calls.append(("diff_stats", since))
        return self.diff

    def read_ref_file(self, worktree, ref, path):
        return self.files_by_ref[(ref, path)]

    def read_file(self, worktree, path):
        return self.files_now[path]


def _guard(git, *, ticket=TICKET, branch="nf/7-ticket-7", since=None):
    return Publisher(git=git, github=None, step_budget=3).guard(
        ticket, "/w", branch=branch, message="m", since=since, empty_check="nothing to push"
    )


def test_an_empty_change_is_refused_with_the_flows_reason():
    git = Git()

    assert _guard(git).failing_check == "nothing to push"
    assert git.calls == [("commit_all", "m"), ("diff_stats", None)]


def test_a_review_fix_diffs_since_its_base():
    git = Git(files=("backend/apps/x.py",))

    guarded = _guard(git, since="abc123")

    assert guarded.failing_check is None
    assert ("diff_stats", "abc123") in git.calls


def test_a_protected_path_is_refused():
    assert _guard(Git(files=(".github/workflows/ci.yml",))).failing_check == (
        "protected path changed"
    )


def test_a_deps_ticket_may_not_change_a_manifest_beyond_dependencies():
    old = '[project]\nname = "a"\ndependencies = []\n'
    new = '[project]\nname = "b"\ndependencies = []\n'
    git = Git(
        files=("backend/pyproject.toml",),
        files_by_ref={("origin/main", "backend/pyproject.toml"): old},
        files_now={"backend/pyproject.toml": new},
    )
    ticket = Ticket(number=7, title="Ticket 7", labels=frozenset({"deps-change"}))

    failing = _guard(git, ticket=ticket).failing_check

    assert failing is not None and failing.startswith("dependency file changed beyond")


def test_the_push_target_is_asserted_after_the_guard():
    with pytest.raises(Exception, match="nf/8"):
        _guard(Git(files=("backend/apps/x.py",)), branch="nf/8-other")
