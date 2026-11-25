from pathlib import Path

import pytest

from factory.config import FactoryConfigError, Settings


def test_from_env_reads_models_and_defaults(monkeypatch):
    monkeypatch.delenv("FACTORY_MODEL", raising=False)
    monkeypatch.delenv("FACTORY_STRONG_MODEL", raising=False)
    monkeypatch.delenv("FACTORY_MAX_TICKETS", raising=False)
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "deepseek/deepseek-flash",
            "FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro",
        }
    )
    assert settings.factory_model == "deepseek/deepseek-flash"
    assert settings.factory_strong_model == "deepseek/deepseek-v4-pro"
    assert settings.max_tickets == 1


def test_from_env_defaults_the_step_budget_to_three():
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "deepseek/deepseek-flash",
            "FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro",
        }
    )
    assert settings.attempts == 3


def test_from_env_missing_default_model_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_MODEL"):
        Settings.from_env({"FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro"})


def test_from_env_missing_strong_model_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_STRONG_MODEL"):
        Settings.from_env({"FACTORY_MODEL": "deepseek/deepseek-flash"})


def test_from_env_max_tickets_parses_int():
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "m",
            "FACTORY_STRONG_MODEL": "s",
            "FACTORY_MAX_TICKETS": "3",
        }
    )
    assert settings.max_tickets == 3


def test_from_env_reads_the_run_limits_and_defaults_them():
    settings = Settings.from_env({"FACTORY_MODEL": "m", "FACTORY_STRONG_MODEL": "s"})
    assert settings.max_open_prs == 2
    assert settings.max_tickets_per_day == 6
    assert settings.state_dir == Path.home() / "factory" / "state"

    overridden = Settings.from_env(
        {
            "FACTORY_MODEL": "m",
            "FACTORY_STRONG_MODEL": "s",
            "FACTORY_MAX_OPEN_PRS": "4",
            "FACTORY_MAX_TICKETS_PER_DAY": "9",
            "FACTORY_STATE_DIR": "/tmp/factory-state",
        }
    )
    assert overridden.max_open_prs == 4
    assert overridden.max_tickets_per_day == 9
    assert overridden.state_dir == Path("/tmp/factory-state")


@pytest.mark.parametrize("name", ["FACTORY_MAX_OPEN_PRS", "FACTORY_MAX_TICKETS_PER_DAY"])
def test_from_env_rejects_non_positive_run_limits(name):
    with pytest.raises(FactoryConfigError, match=name):
        Settings.from_env(
            {
                "FACTORY_MODEL": "m",
                "FACTORY_STRONG_MODEL": "s",
                name: "0",
            }
        )


def test_from_env_bad_max_tickets_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_MAX_TICKETS"):
        Settings.from_env(
            {
                "FACTORY_MODEL": "m",
                "FACTORY_STRONG_MODEL": "s",
                "FACTORY_MAX_TICKETS": "nope",
            }
        )


def test_from_env_defaults_to_the_srv_factory_layout():
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "m",
            "FACTORY_STRONG_MODEL": "s",
        }
    )
    assert settings.repo_dir == Path("/srv/factory/repo")
    assert settings.worktrees_dir == Path("/srv/factory/worktrees")
    assert settings.logs_dir == Path.home() / "factory" / "logs"


def test_from_env_reads_dir_overrides():
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "m",
            "FACTORY_STRONG_MODEL": "s",
            "FACTORY_REPO_DIR": "/tmp/repo",
            "FACTORY_WORKTREES_DIR": "/tmp/worktrees",
            "FACTORY_LOGS_DIR": "/tmp/logs",
        }
    )
    assert settings.repo_dir == Path("/tmp/repo")
    assert settings.worktrees_dir == Path("/tmp/worktrees")
    assert settings.logs_dir == Path("/tmp/logs")


def test_from_env_reads_the_bot_user_id_for_commits():
    settings = Settings.from_env(
        {
            "FACTORY_MODEL": "m",
            "FACTORY_STRONG_MODEL": "s",
            "XOLO_BOT_USER_ID": "12345",
        }
    )
    assert settings.github_user_id == "12345"


def test_from_env_turns_the_pre_pr_review_on_by_default_and_reads_the_switch():
    base = {
        "FACTORY_MODEL": "deepseek/deepseek-flash",
        "FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro",
    }
    assert Settings.from_env(base).pre_pr_review is True
    assert Settings.from_env({**base, "FACTORY_PRE_PR_REVIEW": "0"}).pre_pr_review is False


def test_from_env_turns_the_self_update_on_by_default_and_reads_the_switch():
    base = {
        "FACTORY_MODEL": "deepseek/deepseek-flash",
        "FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro",
    }
    assert Settings.from_env(base).self_update is True
    assert Settings.from_env({**base, "FACTORY_SELF_UPDATE": "0"}).self_update is False


def test_from_env_reads_the_agent_config_home():
    base = {
        "FACTORY_MODEL": "deepseek/deepseek-flash",
        "FACTORY_STRONG_MODEL": "deepseek/deepseek-v4-pro",
    }
    assert Settings.from_env(base).agent_config_home == Path("/srv/factory/agent-config")
    custom = Settings.from_env({**base, "FACTORY_AGENT_CONFIG_HOME": "/opt/agent-config"})
    assert custom.agent_config_home == Path("/opt/agent-config")
