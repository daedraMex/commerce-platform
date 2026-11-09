from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[3] / "docs" / "factory.md"


def test_runbook_smoke_test_checks_git_and_the_check_runner():
    text = RUNBOOK.read_text()

    assert "git -C /srv/factory/repo worktree add" in text
    assert "git -C /srv/factory/repo worktree remove --force" in text
    assert "sudo -u factory-agent git -C /srv/factory/worktrees/" in text
    assert "sudo -u factory sudo -n -u factory-agent --" in text
    assert "sudo: a password is required" in text


def test_runbook_documents_the_sudoers_migration():
    text = RUNBOOK.read_text()

    assert "/etc/sudoers.d/factory-agent" in text
    assert "sudo rm -f /etc/sudoers.d/factory" in text
    assert "sudo visudo -c" in text


def test_runbook_says_run_the_preflight_after_any_change():
    text = RUNBOOK.read_text()

    assert "uv run factory preflight" in text
    assert "first after any machine or factory change" in text


def test_runbook_documents_the_agent_owned_provider_key():
    text = RUNBOOK.read_text()

    assert "sudo -u factory-agent -H /usr/bin/opencode auth login" in text
    assert "sudo -u factory-agent -H /usr/bin/opencode auth list" in text
    assert "FACTORY_PROVIDER_ENV_VARS=" not in text
    assert "DEEPSEEK_API_KEY=" not in text


def test_runbook_documents_the_effective_no_logging_policy_check():
    text = RUNBOOK.read_text()

    assert "Defaults:factory !log_allowed" in text
    assert "sudo -n -l" in text
    assert "Matching Defaults entries" in text
    assert "stay `root:root`" in text
    assert "sudo chown root:factory /etc/sudoers.d/factory-agent" not in text
    assert "sudo chmod 0440 /etc/sudoers.d/factory-agent" not in text


def test_runbook_says_rotate_any_secret_that_appeared_in_logs():
    text = " ".join(RUNBOOK.read_text().lower().split())

    assert "appears in the journal" in text
    assert "treat it as compromised and **rotate it**" in text


def test_runbook_documents_the_bot_commit_identity():
    text = RUNBOOK.read_text()

    assert "XOLO_BOT_USER_ID=1234567" in text
    assert "xolo-bot[bot]" in text
    assert "git var GIT_AUTHOR_IDENT" in text
    assert "the bot commit identity" in text


def test_runbook_documents_the_safe_repo_group_and_fix_commands():
    text = RUNBOOK.read_text()

    assert "clone must belong to group `factory`" in text
    assert "sudo chgrp -R factory /srv/factory/repo" in text
    assert "sudo chmod -R g-s /srv/factory/repo" in text
    assert "sudo chmod -R g-w,o-w /srv/factory/repo" in text


def test_runbook_records_the_ratchet_rule():
    text = " ".join(RUNBOOK.read_text().lower().split())

    assert (
        "every bug found in a factory pr review or a failed night becomes a test "
        "or a preflight step in the same fix" in text
    )
