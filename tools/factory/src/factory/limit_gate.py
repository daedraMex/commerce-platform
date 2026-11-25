"""Whether this hour may work at all: GitHub reachable, the caps, the pause (#147)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .notify import PausedInfo

FACTORY_BOT_LOGIN = "xolo-bot"
FACTORY_BRANCH_PREFIX = "nf/"


@dataclass(frozen=True)
class Limits:
    token: str | None
    open_prs: int
    paused_for: str | None = None


class LimitGate:
    def __init__(
        self,
        *,
        settings,
        github,
        token_provider,
        ledger,
        pause_state,
        notify_paused: Callable[[PausedInfo], None],
    ):
        self.settings = settings
        self.github = github
        self.token_provider = token_provider
        self.ledger = ledger
        self.pause_state = pause_state
        self._notify_paused = notify_paused

    def limits(self) -> Limits:
        """Mint a token, read the open-PR count and check the daily cap.

        The open-PR cap is not applied here: a review fix on an existing PR
        must still run when the cap is reached. It is checked before a new
        ticket is picked (``open_pr_cap``). The daily cap does apply to every
        attempt.
        """
        try:
            token = self.token_provider.mint(self.settings.repo)
            open_prs = self.github.count_open_factory_prs(
                author=FACTORY_BOT_LOGIN,
                branch_prefix=FACTORY_BRANCH_PREFIX,
                token=token,
            )
        except Exception:
            return Limits(None, 0, "GitHub unreachable")
        if self.ledger.count_today() >= self.settings.max_tickets_per_day:
            return Limits(token, open_prs, "daily limit reached")
        return Limits(token, open_prs)

    def open_pr_cap(self, open_prs: int) -> str | None:
        """The pause reason when no new ticket may start, else None."""
        if open_prs < self.settings.max_open_prs:
            return None
        noun = "PR" if open_prs == 1 else "PRs"
        return f"{open_prs} {noun} waiting for review"

    def pause(self, reason: str) -> None:
        """Pause; only the first hour of a pause sends a message."""
        if self.pause_state.enter(reason):
            self._notify_paused(PausedInfo(reason=reason))

    def resume(self) -> None:
        self.pause_state.clear()
