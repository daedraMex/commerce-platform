import pytest

from factory.config import FactoryConfigError
from factory.models import select_model


def test_default_model_for_plain_ticket():
    assert (
        select_model(
            frozenset(),
            default_model="deepseek/deepseek-flash",
            strong_model="deepseek/deepseek-v4-pro",
        )
        == "deepseek/deepseek-flash"
    )


def test_strong_model_for_labeled_ticket():
    assert (
        select_model(
            frozenset({"strong-model"}),
            default_model="deepseek/deepseek-flash",
            strong_model="deepseek/deepseek-v4-pro",
        )
        == "deepseek/deepseek-v4-pro"
    )


def test_missing_default_model_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_MODEL"):
        select_model(frozenset(), default_model=None, strong_model="s")


def test_missing_strong_model_for_strong_ticket_fails_clearly():
    with pytest.raises(FactoryConfigError, match="FACTORY_STRONG_MODEL"):
        select_model(frozenset({"strong-model"}), default_model="m", strong_model=None)
