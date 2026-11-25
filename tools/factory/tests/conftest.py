import pytest

from factory.run_lock import LOCK_ENV


@pytest.fixture(autouse=True)
def _no_inherited_run_lock(monkeypatch):
    """A test's run lock never leaks into the next test through os.environ."""
    monkeypatch.setenv(LOCK_ENV, "")
