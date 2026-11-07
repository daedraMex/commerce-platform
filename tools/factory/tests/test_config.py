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


def test_from_env_bad_max_tickets_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_MAX_TICKETS"):
        Settings.from_env(
            {
                "FACTORY_MODEL": "m",
                "FACTORY_STRONG_MODEL": "s",
                "FACTORY_MAX_TICKETS": "nope",
            }
        )
