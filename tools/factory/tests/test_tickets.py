from pathlib import PurePosixPath

import pytest

from factory.tickets import (
    Contracts,
    Ticket,
    branch_from_worktree_dir_name,
    branch_name,
    is_ready,
    parse_blocked_by,
    parse_contracts,
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


def test_push_target_must_be_the_ticket_s_own_factory_branch():
    from factory.tickets import PushTargetError, assert_push_target

    ticket = Ticket(number=7, title="Widget endpoint", body="", labels=frozenset())

    assert_push_target(branch_name(ticket), ticket)
    assert_push_target("nf/7-an-older-title", ticket)
    for branch in ("main", "nf/8-widget-endpoint", "nf/7", "feature/7-x", "nf/7-x/../main"):
        with pytest.raises(PushTargetError):
            assert_push_target(branch, ticket)


def test_every_branch_the_factory_derives_passes_its_own_push_guard():
    from factory.tickets import assert_push_target

    words = "add the console product list page with filters and the bulk edit form now".split()
    titles = [" ".join(words[:n]) for n in range(1, len(words) + 1)]
    titles += ["x" * n + " y" for n in range(55, 72)]
    titles += ["Ñandú über café", "日本語のタイトル", "", "---"]
    for title in titles:
        ticket = Ticket(number=7, title=title, body="", labels=frozenset())
        assert_push_target(branch_name(ticket), ticket)


CHANGES_STATES = """## Mode

AFK

## Contracts

Changes `photos.submission-states`: remove on a group photo is refused.

## Acceptance criteria
"""


def test_parse_contracts_reads_the_section_by_verb():
    body = (
        "## Contracts\n\n"
        "Defines `orders.place-order-task`; changes `photos.submission-states`; "
        "consumes `photos.catalog-port` (cover rules) and `photos.processing-queue`.\n\n"
        "## Blocked by\n\n- #12\n"
    )

    contracts = parse_contracts(body)

    assert contracts.held == {"orders.place-order-task", "photos.submission-states"}
    assert contracts.consumed == {"photos.catalog-port", "photos.processing-queue"}


def test_parse_contracts_ignores_paths_and_text_outside_the_section():
    body = (
        "Touches `photos.submission-states` in passing.\n\n"
        "## Contracts\n\n"
        "Consumes `photos.submission-states`; see `docs/contracts/photos.md`.\n\n"
        "## Acceptance criteria\n\n- [ ] Update `docs/contracts/photos.md`.\n"
    )

    contracts = parse_contracts(body)

    assert contracts.held == frozenset()
    assert contracts.consumed == {"photos.submission-states"}


def test_parse_contracts_reads_a_plain_line_too():
    body = "**Contracts:** Changes `photos.submission-states`.\n\nMore text.\n"

    assert parse_contracts(body).held == {"photos.submission-states"}


def test_a_ticket_without_contracts_or_with_none_holds_nothing():
    for body in ("## What to build\n\nA page.\n", "## Contracts\n\nNone.\n\n## Mode\n"):
        contracts = parse_contracts(body)
        assert not contracts.held and not contracts.consumed


def test_an_id_without_a_verb_is_held_to_stay_on_the_safe_side():
    body = "## Contracts\n\n`photos.submission-states` (group remove).\n"

    assert parse_contracts(body).held == {"photos.submission-states"}


@pytest.mark.parametrize(
    ("mine", "theirs", "conflict"),
    [
        (Contracts(held=frozenset({"a.x"})), Contracts(held=frozenset({"a.x"})), {"a.x"}),
        (Contracts(held=frozenset({"a.x"})), Contracts(consumed=frozenset({"a.x"})), {"a.x"}),
        (Contracts(consumed=frozenset({"a.x"})), Contracts(held=frozenset({"a.x"})), {"a.x"}),
        (Contracts(consumed=frozenset({"a.x"})), Contracts(consumed=frozenset({"a.x"})), set()),
        (Contracts(held=frozenset({"a.x"})), Contracts(held=frozenset({"a.y"})), set()),
    ],
)
def test_contracts_conflict_unless_both_only_consume(mine, theirs, conflict):
    assert mine.conflicts_with(theirs) == conflict


def test_a_ticket_whose_contract_an_open_pr_holds_is_not_ready():
    ticket = Ticket(
        number=7,
        title="t",
        labels=frozenset({"ready-for-agent"}),
        contract_conflicts=("photos.submission-states held by PR #175 (#156)",),
    )

    assert not is_ready(ticket)


def test_select_skips_a_ticket_that_conflicts_with_one_already_selected():
    first = Ticket(number=7, title="a", body=CHANGES_STATES, labels=frozenset({"ready-for-agent"}))
    second = Ticket(number=8, title="b", body=CHANGES_STATES, labels=frozenset({"ready-for-agent"}))
    other = Ticket(number=9, title="c", labels=frozenset({"ready-for-agent"}))

    assert select_tickets([first, second, other], max_tickets=2) == [first, other]


@pytest.mark.parametrize(
    "line",
    [
        "Consumes `photos.processing-queue` and changes `photos.submission-states`.",
        "Consumes `photos.processing-queue`, changes `photos.submission-states`.",
        "Consumes `photos.processing-queue`. Changes `photos.submission-states`.",
    ],
)
def test_each_id_takes_the_nearest_verb_before_it(line):
    contracts = parse_contracts(f"## Contracts\n\n{line}\n")

    assert contracts.held == {"photos.submission-states"}
    assert contracts.consumed == {"photos.processing-queue"}


def test_a_fenced_example_is_not_the_contracts_section():
    body = (
        "## Notes\n\n```markdown\n## Contracts\n\nConsumes `a.example`.\n```\n\n"
        "## Contracts\n\nChanges `photos.submission-states`.\n"
    )

    contracts = parse_contracts(body)

    assert contracts.held == {"photos.submission-states"}
    assert "a.example" not in contracts.consumed


@pytest.mark.parametrize(
    "body",
    [
        "#### Contracts\n\nChanges `photos.submission-states`.\n",
        "**Contracts** Changes `photos.submission-states`.\n",
    ],
)
def test_other_heading_shapes_are_read(body):
    assert parse_contracts(body).held == {"photos.submission-states"}
