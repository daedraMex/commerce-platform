from pathlib import PurePosixPath

from factory.tickets import (
    Ticket,
    branch_from_worktree_dir_name,
    branch_name,
    is_ready,
    parse_blocked_by,
    select_tickets,
    worktree_path,
)


def _ticket(number, *, labels=(), blocked_by=(), has_open_pr=False):
    return Ticket(
        number=number,
        title=f"Ticket {number}",
        labels=frozenset(labels),
        blocked_by=tuple(blocked_by),
        has_open_pr=has_open_pr,
    )


def test_select_takes_only_ready_labeled():
    tickets = [
        _ticket(1, labels={"ready-for-agent"}),
        _ticket(2, labels={"needs-triage"}),
    ]
    assert [t.number for t in select_tickets(tickets, max_tickets=5)] == [1]


def test_select_skips_needs_decision():
    tickets = [
        _ticket(1, labels={"ready-for-agent", "needs-decision"}),
        _ticket(2, labels={"ready-for-agent"}),
    ]
    assert [t.number for t in select_tickets(tickets, max_tickets=5)] == [2]


def test_select_skips_tickets_with_open_blockers():
    tickets = [
        _ticket(1, labels={"ready-for-agent"}, blocked_by=(5,)),
        _ticket(2, labels={"ready-for-agent"}),
    ]
    assert [t.number for t in select_tickets(tickets, max_tickets=5)] == [2]


def test_select_skips_tickets_with_open_pr():
    tickets = [
        _ticket(1, labels={"ready-for-agent"}, has_open_pr=True),
        _ticket(2, labels={"ready-for-agent"}),
    ]
    assert [t.number for t in select_tickets(tickets, max_tickets=5)] == [2]


def test_select_is_oldest_first():
    tickets = [
        _ticket(9, labels={"ready-for-agent"}),
        _ticket(3, labels={"ready-for-agent"}),
        _ticket(7, labels={"ready-for-agent"}),
    ]
    assert [t.number for t in select_tickets(tickets, max_tickets=5)] == [3, 7, 9]


def test_select_respects_max_tickets():
    tickets = [_ticket(n, labels={"ready-for-agent"}) for n in range(1, 6)]
    assert [t.number for t in select_tickets(tickets, max_tickets=2)] == [1, 2]


def test_parse_blocked_by_line():
    body = "Some notes.\nBlocked by: #12, #34\nMore notes."
    assert parse_blocked_by(body) == (12, 34)


def test_parse_blocked_by_missing_returns_empty():
    assert parse_blocked_by("No blockers here.") == ()


def test_branch_name_is_deterministic_and_safe():
    ticket = Ticket(number=42, title="Add Dark Mode!")
    assert branch_name(ticket) == "nf/42-add-dark-mode"


def test_worktree_path_is_flat_and_matches_the_sudoers_glob(tmp_path):
    worktrees = tmp_path / "worktrees"
    path = worktree_path(worktrees, "nf/46-add-dark-mode")

    assert path == worktrees / "nf-46-add-dark-mode"
    assert path.parent == worktrees
    assert path.name == "nf-46-add-dark-mode"
    assert PurePosixPath(str(path)).match(str(worktrees / "*"))
    assert PurePosixPath(str(path / "backend" / "scripts" / "check.sh")).match(
        str(worktrees / "*" / "backend" / "scripts" / "check.sh")
    )


def test_worktree_path_rejects_a_nested_branch_component(tmp_path):
    worktrees = tmp_path / "worktrees"
    assert "/" not in worktree_path(worktrees, "nf/46-slug").name


def test_branch_from_worktree_dir_name_recovers_factory_branches():
    assert branch_from_worktree_dir_name("nf-46-add-dark-mode") == "nf/46-add-dark-mode"
    assert branch_from_worktree_dir_name("preflight-42") == "preflight-42"


def test_is_ready_requires_ready_label():
    assert not is_ready(_ticket(1, labels={"needs-triage"}))
