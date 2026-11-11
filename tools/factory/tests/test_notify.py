import io
import json
from urllib.error import HTTPError

from factory.notify import (
    PausedInfo,
    PrReadyInfo,
    RunFailedInfo,
    StuckInfo,
    TelegramNotifier,
    build_handoff_command,
    build_paused_message,
    build_pr_ready_keyboard,
    build_pr_ready_message,
    build_run_failed_message,
    build_stuck_message,
    escape_html,
)


def _pr_ready(**overrides):
    fields = dict(
        ticket_number=7,
        ticket_title="Add <widget> endpoint",
        branch="factory/7-add-widget",
        model="deepseek/deepseek-flash",
        files=(("backend/apps/x/views.py", 10, 2),),
        new_tests=("backend/tests/api/test_x.py",),
        check_status="pass",
        migrations_changed=False,
        decisions="- Chose A over B.",
        pr_url="https://github.com/r/pull/1",
        diff_url="https://github.com/r/pull/1.diff",
        ticket_url="https://github.com/r/issues/7",
    )
    fields.update(overrides)
    return PrReadyInfo(**fields)


def _stuck(**overrides):
    fields = dict(
        ticket_number=7,
        ticket_title="Add widget",
        model="deepseek/deepseek-flash",
        attempts=5,
        failing_check="scripts/check.sh",
        open_question="Should it be a POST?",
        comment_url="https://github.com/r/issues/7#comment-1",
        ticket_url="https://github.com/r/issues/7",
        log_path="/home/factory/factory/logs/7.log",
        worktree="/home/factory/factory/worktrees/nf/7-add-widget",
        handoff_command="ssh factory@host && cd /home/factory/factory/worktrees/nf/7-add-widget",
    )
    fields.update(overrides)
    return StuckInfo(**fields)


def test_pr_ready_message_contains_required_fields():
    msg = build_pr_ready_message(_pr_ready())
    assert "#7" in msg
    assert "factory/7-add-widget" in msg
    assert "deepseek/deepseek-flash" in msg
    assert "pass" in msg
    assert "New tests: backend/tests/api/test_x.py" in msg
    assert "Chose A over B." in msg


def test_pr_ready_message_escapes_html():
    msg = build_pr_ready_message(_pr_ready())
    assert "&lt;widget&gt;" in msg
    assert "<widget>" not in msg


def test_pr_ready_message_notes_migrations():
    msg = build_pr_ready_message(_pr_ready(migrations_changed=True))
    assert "Migrations: yes" in msg


def test_stuck_message_contains_required_fields():
    msg = build_stuck_message(_stuck())
    assert "#7" in msg
    assert "deepseek/deepseek-flash" in msg
    assert "Attempts: 5" in msg
    assert "scripts/check.sh" in msg
    assert "Should it be a POST?" in msg
    assert "/home/factory/factory/logs/7.log" in msg


def test_stuck_message_omits_question_when_none():
    msg = build_stuck_message(_stuck(open_question=None))
    assert "Open question" not in msg


def test_messages_carry_no_secrets_or_code():
    secret = "tg-BOT-TOKEN-123"
    code = "def steal(): ..."
    pr = build_pr_ready_message(_pr_ready())
    stuck = build_stuck_message(_stuck())
    for msg in (pr, stuck):
        assert secret not in msg
        assert code not in msg


def test_stuck_message_shows_log_path_not_content():
    msg = build_stuck_message(_stuck())
    assert "/home/factory/factory/logs/7.log" in msg
    assert "Traceback (most recent call last)" not in msg


def test_stuck_message_includes_handoff_command():
    msg = build_stuck_message(_stuck())
    assert "/home/factory/factory/worktrees/nf/7-add-widget" in msg
    assert "ssh factory@host &amp;&amp; cd /home/factory/factory/worktrees/nf/7-add-widget" in msg


def test_run_failed_message_names_the_reason_and_escapes_html():
    msg = build_run_failed_message(
        RunFailedInfo(reason="could not fetch origin/main: fatal <no network>")
    )
    assert "Night factory aborted" in msg
    assert "could not fetch origin/main" in msg
    assert "&lt;no network&gt;" in msg


def test_paused_message_names_the_reason_and_escapes_html():
    msg = build_paused_message(PausedInfo(reason="2 PRs waiting for review <x>"))
    assert "Night factory paused" in msg
    assert "2 PRs waiting for review &lt;x&gt;" in msg


def test_build_handoff_command_with_and_without_host():
    assert build_handoff_command(host="factory@host", worktree="/w") == "ssh factory@host && cd /w"
    assert build_handoff_command(host=None, worktree="/w") == "cd /w"


def test_escape_html():
    assert escape_html("a<b>&c>") == "a&lt;b&gt;&amp;c&gt;"


def test_telegram_notifier_posts_to_one_chat_id():
    sent = {}

    def post(url, payload):
        sent["url"] = url
        sent["payload"] = payload

    notifier = TelegramNotifier("token123", "chat456", post=post)
    notifier.send_stuck(_stuck())
    assert "chat456" == sent["payload"]["chat_id"]
    assert "parse_mode" in sent["payload"]
    assert "reply_markup" in sent["payload"]
    assert "token123" in sent["url"]
    assert "getUpdates" not in sent["url"]


def _assert_valid_html(text):
    index = 0
    while (index := text.find("&", index)) != -1:
        assert any(text.startswith(entity, index) for entity in ("&amp;", "&lt;", "&gt;"))
        index += 1
    if "<" in text:
        assert text.rfind("<") < text.rfind(">")


def test_pr_ready_message_stays_within_telegram_limit_with_huge_inputs():
    tests = tuple(f"backend/tests/api/test_very_long_case_name_{i}.py" for i in range(300))
    decisions = "- A very long decision. " * 2000
    info = _pr_ready(new_tests=tests, decisions=decisions)

    message = build_pr_ready_message(info)

    assert len(message) <= 4096
    assert message.startswith("<b>PR ready</b>")
    assert message.endswith("… full text in the PR")
    assert "+" in message and "more" in message
    assert build_pr_ready_keyboard(info)[0][0]["text"] == "PR"
    _assert_valid_html(message)


def test_pr_ready_message_truncates_new_tests_before_decisions():
    tests = tuple(f"backend/tests/api/test_case_{i}.py" for i in range(500))
    decisions = "- Keep this decision."
    message = build_pr_ready_message(_pr_ready(new_tests=tests, decisions=decisions))

    assert len(message) <= 4096
    assert decisions in message
    assert "+" in message and "more" in message
    assert message.endswith("… full text in the PR")


def test_pr_ready_message_truncates_decisions_without_splitting_entities_or_tags():
    decisions = "<&>" * 5000
    message = build_pr_ready_message(_pr_ready(new_tests=(), decisions=decisions))

    assert len(message) <= 4096
    assert message.startswith("<b>PR ready</b>")
    assert "<b>Decisions</b>" in message
    assert message.endswith("… full text in the PR")
    _assert_valid_html(message)


def test_telegram_notifier_logs_and_swallows_http_errors(capsys):
    def post(url, payload):
        body = io.BytesIO(
            json.dumps({"ok": False, "description": "Bad Request: message is too long"}).encode()
        )
        raise HTTPError(url, 400, "Bad Request", {}, body)

    notifier = TelegramNotifier("token123", "chat456", post=post)

    notifier.send_pr_ready(_pr_ready())

    err = capsys.readouterr().err
    assert "status=400" in err
    assert "message is too long" in err
    assert "token123" not in err
    assert "chat456" not in err


def test_telegram_notifier_logs_and_swallows_unexpected_errors(capsys):
    def post(url, payload):
        raise RuntimeError(f"{url} {payload['chat_id']}")

    notifier = TelegramNotifier("token123", "chat456", post=post)

    notifier.send_stuck(_stuck())

    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "token123" not in err
    assert "chat456" not in err
