import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[3] / "docs" / "factory.md"


def test_runbook_smoke_test_checks_git_and_the_check_runner():
    text = RUNBOOK.read_text()

    assert "git -C /srv/factory/repo worktree add" in text
    assert "git -C /srv/factory/repo worktree remove --force" in text
    assert "sudo -u factory-agent git -C /srv/factory/worktrees/" in text
    assert "sudo -u factory sudo -n -u factory-agent --" in text
    assert "sudo: a password is required" in text


def test_runbook_documents_the_console_toolchain_setup():
    text = RUNBOOK.read_text()

    assert "Install the console toolchain (admin user)" in text
    assert "corepack enable" in text
    assert "playwright@1.65.0 install-deps chromium" in text
    assert "/srv/factory/worktrees/*/web/console/scripts/check.sh" in text
    assert "sudo -u factory-agent /usr/bin/pkill -KILL -u factory-agent" in text
    assert "pgrep -u factory-agent" in text


def test_runbook_documents_the_sudoers_migration():
    text = RUNBOOK.read_text()

    assert "/etc/sudoers.d/factory-agent" in text
    assert "sudo rm -f /etc/sudoers.d/factory" in text
    assert "sudo visudo -c" in text


def test_runbook_says_run_the_preflight_after_any_change():
    text = RUNBOOK.read_text()

    assert "uv run --locked factory preflight" in text
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


def test_runbook_documents_agent_owned_worktree_cleanup():
    text = RUNBOOK.read_text()
    flat = " ".join(text.split())

    assert "sudoers-allowed `rm -rf`" in flat
    assert "not live git worktrees" in flat
    assert "group `factory-agent` and mode `0770`" in flat
    assert "git worktree prune" in flat
    assert "PYTEST_ADDOPTS=-p no:cacheprovider" in text


def test_runbook_documents_the_self_update():
    text = RUNBOOK.read_text()
    flat = " ".join(text.split())

    assert "## Updating the factory" in text
    assert "preflight ok at <sha> (N tickets listed)" in flat
    assert "It never resets or discards anything there" in flat
    assert "FACTORY_SELF_UPDATE=0" in text


def test_runbook_documents_fresh_run_homes():
    text = RUNBOOK.read_text()
    flat = " ".join(text.split())

    assert "/usr/bin/rm -rf /srv/factory/agent-homes/*" in text
    assert "sudo install -d -m 2770 -o factory -g factory-work /srv/factory/agent-homes" in text
    assert "sudo apt install ripgrep" in text
    assert "/home/factory/factory/agent-auth.json" in text
    assert "run that `install` line again" in flat


def test_runbook_documents_the_undeclared_contract_check():
    flat = " ".join(RUNBOOK.read_text().split())

    assert "edits but the ticket does not declare as changed" in flat
    assert "declared as consumed" in flat
    assert "Review fixes are not checked again" in flat


def test_runbook_documents_model_checks_and_reviewer_failures():
    flat = " ".join(RUNBOOK.read_text().split())

    assert "fails naming a model that gives none" in flat
    assert "model-checks.json" in flat
    assert "the reviewer produced no output (exit N)" in flat
    assert "Pre-PR reviewer failing" in flat
    assert "review fix step N" in flat


def test_runbook_documents_interrupted_runs_and_closed_tickets():
    flat = " ".join(RUNBOOK.read_text().split())

    assert "kills every agent process" in flat
    assert "the group kill is refused and ignored" in flat
    assert "preflight cleanup failed after <step>" in flat
    assert "Night factory cleaned up" in flat
    assert "Never run two preflights at once" in flat
    assert "closed while the factory worked on it" in flat


def test_runbook_documents_the_safe_repo_group_and_fix_commands():
    text = RUNBOOK.read_text()

    assert "clone must belong to group `factory`" in text
    assert "sudo chgrp -R factory /srv/factory/repo" in text
    assert "sudo chmod -R g-s /srv/factory/repo" in text
    assert "sudo chmod -R g-w,o-w /srv/factory/repo" in text


def test_runbook_documents_the_machine_migration_checklist():
    text = RUNBOOK.read_text()
    flat = " ".join(text.split())

    assert "## Migrating an existing machine" in text
    assert "Update `/etc/sudoers.d/factory-agent`" in flat
    assert "validate it with `sudo visudo -c`" in flat
    assert "Run `opencode auth login` as `factory-agent`" in flat
    assert "Remove `DEEPSEEK_API_KEY` and `FACTORY_PROVIDER_ENV_VARS`" in flat
    assert "add `XOLO_BOT_USER_ID`" in flat
    assert "Rotate the DeepSeek key and the Postgres password" in flat
    assert "Clean any leftover worktrees, then run `factory preflight`" in flat


def test_runbook_records_the_ratchet_rule():
    text = " ".join(RUNBOOK.read_text().lower().split())

    assert (
        "every bug found in a factory pr review or a failed night becomes a test "
        "or a preflight step in the same fix" in text
    )


def test_runbook_documents_the_final_sudoers_file_exactly():
    text = RUNBOOK.read_text()
    flat = " ".join(text.split())
    lines = (
        "Defaults:factory !log_allowed",
        "Defaults>factory-agent umask=0007",
        "Defaults>factory-agent umask_override",
        "factory ALL=(factory-agent) NOPASSWD:SETENV: /usr/bin/opencode, "
        "/usr/bin/cat, /usr/bin/test, "
        "/srv/factory/worktrees/*/backend/scripts/check.sh, "
        "/srv/factory/worktrees/*/web/console/scripts/check.sh, "
        "/usr/bin/rm -rf /srv/factory/worktrees/*, "
        "/usr/bin/rm -rf /srv/factory/agent-homes/*, "
        "/usr/bin/pkill -KILL -u factory-agent",
    )
    sudoers = "\n".join(f"    {line}" for line in lines)

    assert sudoers in text
    assert "Sudo's `*` does not cross `/`" in flat
    assert "a sudoers glob is not a security boundary for `rm`" in flat
    assert "/usr/bin/install" not in text


def test_runbook_says_to_copy_the_locked_service_units_and_reload():
    text = RUNBOOK.read_text()

    section = text.split("## Migrating an existing machine", 1)[1].split("\n## ", 1)[0]
    assert "uv run --locked" in section
    assert "cp /srv/factory/repo/tools/factory/systemd/factory.service" in section
    assert "cp /srv/factory/repo/tools/factory/systemd/factory-metrics.service" in section
    assert "systemctl --user daemon-reload" in section


def test_runbook_runs_the_factory_with_a_locked_environment():
    # Plain `uv run`/`uv sync` rewrite a stale uv.lock in the checkout, which the
    # self-update then refuses as local changes (#216).
    text = RUNBOOK.read_text()

    assert "uv run factory" not in text
    assert re.search(r"^\s*(cd tools/factory && )?uv sync\s*$", text, re.MULTILINE) is None
