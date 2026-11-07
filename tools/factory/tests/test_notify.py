from factory.notify import (
    PrReadyInfo,
    StuckInfo,
    TelegramNotifier,
    build_pr_ready_message,
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
