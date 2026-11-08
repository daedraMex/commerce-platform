"""Notifications, behind a replaceable Notifier port.

The Telegram implementation only sends to one fixed chat id; it never polls and
never accepts commands. Messages carry no code, diffs or secrets by
construction: the builders only render the fields of the info dataclasses, and
the log is referenced by path, never by content.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib import request
from urllib.error import URLError


class Notifier(Protocol):
    def send_pr_ready(self, info: PrReadyInfo) -> None: ...

    def send_stuck(self, info: StuckInfo) -> None: ...


@dataclass(frozen=True)
class PrReadyInfo:
    ticket_number: int
    ticket_title: str
    branch: str
    model: str
    files: tuple[tuple[str, int, int], ...]
    new_tests: tuple[str, ...]
    check_status: str
    migrations_changed: bool
    decisions: str
    pr_url: str
    diff_url: str
    ticket_url: str


@dataclass(frozen=True)
class StuckInfo:
    ticket_number: int
    ticket_title: str
    model: str
    attempts: int
    failing_check: str
    open_question: str | None
    comment_url: str
    ticket_url: str
    log_path: str
    worktree: str
    handoff_command: str


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pr_ready_message(info: PrReadyInfo) -> str:
    lines = [
        f"<b>PR ready</b> — #{info.ticket_number} {escape_html(info.ticket_title)}",
        f"Branch: <code>{escape_html(info.branch)}</code>",
        f"Model: <code>{escape_html(info.model)}</code>",
        f"Check: {escape_html(info.check_status)}",
        f"Migrations: {'yes' if info.migrations_changed else 'no'}",
        f"Files: {len(info.files)} (+{_sum(info.files, 1)}/−{_sum(info.files, 2)})",
    ]
    if info.new_tests:
        lines.append("New tests: " + ", ".join(escape_html(t) for t in info.new_tests))
    if info.decisions.strip():
        lines += ["", "<b>Decisions</b>", "", escape_html(info.decisions.strip())]
    return "\n".join(lines)


def build_handoff_command(*, host: str | None, worktree: str) -> str:
    if host:
        return f"ssh {host} && cd {worktree}"
    return f"cd {worktree}"


def build_stuck_message(info: StuckInfo) -> str:
    lines = [
        f"<b>Stuck</b> — #{info.ticket_number} {escape_html(info.ticket_title)}",
        f"Model: <code>{escape_html(info.model)}</code>",
        f"Attempts: {info.attempts}",
        f"Failing check: <code>{escape_html(info.failing_check)}</code>",
    ]
    if info.open_question:
        lines += ["", f"Open question: {escape_html(info.open_question)}"]
    lines += [
        "",
        f"Log: {escape_html(info.log_path)}",
        f"Worktree: <code>{escape_html(info.worktree)}</code>",
        f"Enter: <code>{escape_html(info.handoff_command)}</code>",
    ]
    return "\n".join(lines)


def build_pr_ready_keyboard(info: PrReadyInfo) -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "PR", "url": info.pr_url},
            {"text": "Diff", "url": info.diff_url},
            {"text": "Ticket", "url": info.ticket_url},
        ]
    ]


def build_stuck_keyboard(info: StuckInfo) -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "Issue comment", "url": info.comment_url},
            {"text": "Ticket", "url": info.ticket_url},
        ]
    ]


PostFn = Callable[[str, dict], None]


def _http_post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        request.urlopen(req, timeout=30)
    except URLError as exc:
        raise RuntimeError(f"Telegram send failed: {exc}") from exc


class NullNotifier:
    """A notifier that does nothing, used when Telegram is not configured."""

    def send_pr_ready(self, info: PrReadyInfo) -> None:
        return None

    def send_stuck(self, info: StuckInfo) -> None:
        return None


class TelegramNotifier:
    """Send messages to one fixed chat id via the Bot API."""

    def __init__(self, bot_token: str, chat_id: str, post: PostFn = _http_post):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._post = post

    def send_pr_ready(self, info: PrReadyInfo) -> None:
        self._send(build_pr_ready_message(info), build_pr_ready_keyboard(info))

    def send_stuck(self, info: StuckInfo) -> None:
        self._send(build_stuck_message(info), build_stuck_keyboard(info))

    def _send(self, text: str, keyboard: list[list[dict[str, str]]]) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload: dict = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if keyboard:
            payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        self._post(url, payload)


def _sum(files: tuple[tuple[str, int, int], ...], index: int) -> int:
    return sum(row[index] for row in files)
