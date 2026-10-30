import copy

import pytest
from django.conf import settings

from apps.health.views import check_database

pytestmark = pytest.mark.django_db


def test_database_check_does_not_change_global_database_settings():
    before = copy.deepcopy(settings.DATABASES)

    check_database()

    assert settings.DATABASES == before


def test_database_check_keeps_configured_options_and_forces_its_timeouts(monkeypatch):
    captured = {}
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            executed.append(sql)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr("apps.health.views.psycopg.connect", fake_connect)
    monkeypatch.setitem(
        settings.DATABASES["default"],
        "OPTIONS",
        {"sslmode": "require", "options": "-c search_path=public", "connect_timeout": 30},
    )

    check_database()

    assert captured["sslmode"] == "require"
    assert "-c search_path=public" in captured["options"]
    assert "-c statement_timeout=1000" in captured["options"]
    assert captured["connect_timeout"] == 1
    assert executed == ["SELECT 1"]
