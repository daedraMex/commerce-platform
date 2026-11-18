"""Notifications, behind a replaceable Notifier port.

The Telegram implementation only sends to one fixed chat id; it never polls and
never accepts commands. Messages carry no code, diffs or secrets by
construction: the builders only render the fields of the info dataclasses, and
the log is referenced by path, never by content.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

TELEGRAM_MAX_MESSAGE_CHARS = 4096
TRUNCATION_NOTICE = "… full text in the PR"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Notifier(Protocol):
    def send_pr_ready(self, info: PrReadyInfo) -> None: ...

    def send_stuck(self, info: StuckInfo) -> None: ...

    def send_run_failed(self, info: RunFailedInfo) -> None: ...

    def send_paused(self, info: PausedInfo) -> None: ...

    def send_review_addressed(self, info: ReviewAddressedInfo) -> None: ...

    def send_review_skipped(self, info: ReviewSkippedInfo) -> None: ...

    def send_metrics(self, text: str) -> None: ...


@dataclass(frozen=True)
class ReviewSkippedInfo:
    reason: str


@dataclass(frozen=True)
class ReviewAddressedInfo:
    pr_number: int
    ticket_number: int
    branch: str
    model: str
    commit_sha: str
    comments: int
    pr_url: str
    ticket_url: str


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
    worktree: str | None
    handoff_command: str | None
    # Set when needs-decision could not be added; the ticket is then held (#160).
    label_error: str | None = None


@dataclass(frozen=True)
class RunFailedInfo:
    reason: str


@dataclass(frozen=True)
class PausedInfo:
    reason: str


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_prefix(text: str, limit: int) -> str:
    """The longest prefix that fits and never splits an HTML entity or tag."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    index = 0
    last_safe = 0
    while index < limit:
        char = text[index]
        if char == "<":
            end = text.find(">", index)
            if end == -1 or end >= limit:
                return text[:index]
            index = end + 1
            last_safe = index
        elif char == "&":
            end = text.find(";", index)
            if end == -1 or end >= limit:
                return text[:index]
            index = end + 1
            last_safe = index
        else:
            index += 1
            last_safe = index
    return text[:last_safe]


def _tags_to_close(text: str) -> str:
    open_tags: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "<":
            end = text.find(">", index)
            if end == -1:
                break
            tag = text[index + 1 : end].strip()
            if tag.startswith("/"):
                name = tag[1:].split()[0].lower()
                for position in range(len(open_tags) - 1, -1, -1):
                    if open_tags[position] == name:
                        del open_tags[position:]
                        break
            elif tag and not tag.startswith("!") and not tag.endswith("/"):
                open_tags.append(tag.split()[0].lower())
            index = end + 1
        elif char == "&":
            end = text.find(";", index)
            if end == -1:
                break
            index = end + 1
        else:
            index += 1
    return "".join(f"</{name}>" for name in reversed(open_tags))


def _bound_message(text: str) -> str:
    if len(text) <= TELEGRAM_MAX_MESSAGE_CHARS:
        return text
    limit = TELEGRAM_MAX_MESSAGE_CHARS - len(TRUNCATION_NOTICE) - 1
    while limit > 0:
        prefix = _safe_prefix(text, limit)
        result = prefix.rstrip() + _tags_to_close(prefix) + "\n" + TRUNCATION_NOTICE
        if len(result) <= TELEGRAM_MAX_MESSAGE_CHARS:
            return result
        limit -= len(result) - TELEGRAM_MAX_MESSAGE_CHARS
    return _safe_prefix(text, TELEGRAM_MAX_MESSAGE_CHARS)


def _fit_new_tests(tests: tuple[str, ...], limit: int) -> str | None:
    full = "New tests: " + ", ".join(tests)
    if len(full) <= limit:
        return full
    prefix = "New tests: "
    kept: list[str] = []
    for index, test in enumerate(tests):
        remaining = len(tests) - index - 1
        candidate = prefix + ", ".join([*kept, test])
        if remaining:
            candidate += f", +{remaining} more"
        if len(candidate) <= limit:
            kept.append(test)
        else:
            break
    remaining = len(tests) - len(kept)
    if not kept:
        minimal = prefix + f"+{remaining} more"
        return minimal if len(minimal) <= limit else None
    return prefix + ", ".join(kept) + f", +{remaining} more"


def build_pr_ready_message(info: PrReadyInfo) -> str:
    header = "\n".join(
        [
            f"<b>PR ready</b> — #{info.ticket_number} {escape_html(info.ticket_title)}",
            f"Branch: <code>{escape_html(info.branch)}</code>",
            f"Model: <code>{escape_html(info.model)}</code>",
            f"Check: {escape_html(info.check_status)}",
            f"Migrations: {'yes' if info.migrations_changed else 'no'}",
            f"Files: {len(info.files)} (+{_sum(info.files, 1)}/−{_sum(info.files, 2)})",
        ]
    )
    tests = tuple(escape_html(test) for test in info.new_tests)
    decisions = escape_html(info.decisions.strip())

    def render(tests_line: str | None, decisions_text: str, *, truncated: bool) -> str:
        parts = [header]
        if tests_line:
            parts.append(tests_line)
        if decisions_text:
            parts += ["", "<b>Decisions</b>", "", decisions_text]
        if truncated:
            parts += ["", TRUNCATION_NOTICE]
        return "\n".join(parts)

    tests_line = "New tests: " + ", ".join(tests) if tests else None
    message = render(tests_line, decisions, truncated=False)
    if len(message) <= TELEGRAM_MAX_MESSAGE_CHARS:
        return message

    tests_line = None
    if tests:
        base = render(None, decisions, truncated=True)
        tests_line = _fit_new_tests(tests, TELEGRAM_MAX_MESSAGE_CHARS - len(base) - 1)
        if tests_line is None:
            tests_line = f"New tests: +{len(tests)} more"
    message = render(tests_line, decisions, truncated=True)
    if len(message) <= TELEGRAM_MAX_MESSAGE_CHARS:
        return message

    base = render(tests_line, "", truncated=True)
    available = TELEGRAM_MAX_MESSAGE_CHARS - len(base) - len("\n\n<b>Decisions</b>\n\n")
    decisions = _safe_prefix(decisions, available).rstrip()
    return _bound_message(render(tests_line, decisions, truncated=True))


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
    if info.label_error is not None:
        lines += [
            "",
            f"needs-decision was not added: {escape_html(info.label_error)}",
            f"The factory holds #{info.ticket_number} and retries the label each run.",
        ]
    lines += ["", f"Log: {escape_html(info.log_path)}"]
    if info.worktree is not None and info.handoff_command is not None:
        lines += [
            f"Worktree: <code>{escape_html(info.worktree)}</code>",
            f"Enter: <code>{escape_html(info.handoff_command)}</code>",
        ]
    return _bound_message("\n".join(lines))


def build_run_failed_message(info: RunFailedInfo) -> str:
    return _bound_message(
        "\n".join(
            [
                "<b>Night factory aborted</b>",
                escape_html(info.reason),
            ]
        )
    )


def build_paused_message(info: PausedInfo) -> str:
    return _bound_message(
        "\n".join(
            [
                "<b>Night factory paused</b>",
                escape_html(info.reason),
            ]
        )
    )


def build_review_skipped_message(info: ReviewSkippedInfo) -> str:
    return _bound_message(
        "\n".join(
            [
                "<b>Review fixes skipped</b>",
                escape_html(info.reason),
            ]
        )
    )


def build_review_addressed_message(info: ReviewAddressedInfo) -> str:
    return _bound_message(
        "\n".join(
            [
                f"<b>Review addressed</b> — PR #{info.pr_number} (#{info.ticket_number})",
                f"Branch: <code>{escape_html(info.branch)}</code>",
                f"Model: <code>{escape_html(info.model)}</code>",
                f"Commit: <code>{escape_html(info.commit_sha)}</code>",
                f"Review comments: {info.comments}",
            ]
        )
    )


def build_review_addressed_keyboard(
    info: ReviewAddressedInfo,
) -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "PR", "url": info.pr_url},
            {"text": "Ticket", "url": info.ticket_url},
        ]
    ]


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


class TelegramError(RuntimeError):
    def __init__(self, description: str, *, status: int | None = None):
        self.status = status
        self.description = description
        super().__init__(description)


def _telegram_description(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:
        return str(getattr(exc, "reason", ""))
    try:
        payload = json.loads(body)
    except ValueError:
        return body.strip()
    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        return description
    return body.strip()


def _http_post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        raise TelegramError(_telegram_description(exc), status=exc.code) from exc
    except URLError as exc:
        raise TelegramError(str(exc.reason)) from exc


class NullNotifier:
    """A notifier that does nothing, used when Telegram is not configured."""

    def send_pr_ready(self, info: PrReadyInfo) -> None:
        return None

    def send_stuck(self, info: StuckInfo) -> None:
        return None

    def send_run_failed(self, info: RunFailedInfo) -> None:
        return None

    def send_paused(self, info: PausedInfo) -> None:
        return None

    def send_review_addressed(self, info: ReviewAddressedInfo) -> None:
        return None

    def send_review_skipped(self, info: ReviewSkippedInfo) -> None:
        return None

    def send_metrics(self, text: str) -> None:
        pass


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

    def send_run_failed(self, info: RunFailedInfo) -> None:
        self._send(build_run_failed_message(info), [])

    def send_paused(self, info: PausedInfo) -> None:
        self._send(build_paused_message(info), [])

    def send_review_addressed(self, info: ReviewAddressedInfo) -> None:
        self._send(
            build_review_addressed_message(info),
            build_review_addressed_keyboard(info),
        )

    def send_review_skipped(self, info: ReviewSkippedInfo) -> None:
        self._send(build_review_skipped_message(info), [])

    def send_metrics(self, text: str) -> None:
        """Unlike alerts, a lost report must fail the command, so errors propagate."""
        self._send(_bound_message(text), [], raise_errors=True)

    def _send(
        self,
        text: str,
        keyboard: list[list[dict[str, str]]],
        *,
        raise_errors: bool = False,
    ) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload: dict = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if keyboard:
            payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        try:
            self._post(url, payload)
        except Exception as exc:
            if raise_errors:
                raise RuntimeError(f"Telegram send failed: {self._redact(str(exc))}") from None
            self._report(exc)

    def _report(self, error: Exception) -> None:
        if isinstance(error, TelegramError):
            self._log_failure(error.status, error.description)
        elif isinstance(error, HTTPError):
            self._log_failure(error.code, _telegram_description(error))
        elif isinstance(error, URLError):
            self._log_failure(None, str(error.reason))
        else:
            self._log_failure(None, f"{type(error).__name__}: {error}")

    def _log_failure(self, status: int | None, description: str) -> None:
        description = self._redact(description)
        if status is None:
            message = f"Telegram notification failed: {description}"
        else:
            message = f"Telegram notification failed: status={status} description={description}"
        logger.error(message)
        print(message, file=sys.stderr)

    def _redact(self, text: str) -> str:
        text = str(text)
        if self._bot_token:
            text = text.replace(self._bot_token, "<redacted>")
        if self._chat_id:
            text = text.replace(self._chat_id, "<redacted>")
        return text


def _sum(files: tuple[tuple[str, int, int], ...], index: int) -> int:
    return sum(row[index] for row in files)
