from types import SimpleNamespace

from factory.limit_gate import LimitGate


class Pause:
    def __init__(self):
        self.reasons = []

    def enter(self, reason):
        first = reason not in self.reasons
        self.reasons.append(reason)
        return first

    def clear(self):
        self.reasons.clear()


def _gate(*, max_open_prs=2, count_today=0, mint_error=None):
    sent = []

    class Tokens:
        def mint(self, repo):
            if mint_error:
                raise mint_error
            return "TOKEN"

    gate = LimitGate(
        settings=SimpleNamespace(repo="o/r", max_open_prs=max_open_prs, max_tickets_per_day=3),
        github=SimpleNamespace(count_open_factory_prs=lambda **kw: 1),
        token_provider=Tokens(),
        ledger=SimpleNamespace(count_today=lambda: count_today),
        pause_state=Pause(),
        notify_paused=sent.append,
    )
    return gate, sent


def test_limits_read_the_token_the_open_prs_and_the_daily_cap():
    gate, _ = _gate()
    assert gate.limits().token == "TOKEN" and gate.limits().paused_for is None

    gate, _ = _gate(count_today=3)
    assert gate.limits().paused_for == "daily limit reached"

    gate, _ = _gate(mint_error=RuntimeError("down"))
    assert gate.limits().paused_for == "GitHub unreachable"


def test_the_open_pr_cap_names_the_waiting_prs_and_pauses_once():
    gate, sent = _gate(max_open_prs=2)

    assert gate.open_pr_cap(1) is None
    assert gate.open_pr_cap(1 + 1) == "2 PRs waiting for review"

    gate.pause("2 PRs waiting for review")
    gate.pause("2 PRs waiting for review")
    assert [info.reason for info in sent] == ["2 PRs waiting for review"]
