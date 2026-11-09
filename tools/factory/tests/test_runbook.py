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


def test_runbook_records_the_ratchet_rule():
    text = " ".join(RUNBOOK.read_text().lower().split())

    assert (
        "every bug found in a factory pr review or a failed night becomes a test "
        "or a preflight step in the same fix" in text
    )
