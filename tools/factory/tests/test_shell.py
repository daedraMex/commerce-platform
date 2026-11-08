from factory.shell import merge_env


def test_merge_env_removes_none_keys(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("KEEP", "value")
    env = merge_env({"GH_TOKEN": None, "NEW": "x"})
    assert "GH_TOKEN" not in env
    assert env["KEEP"] == "value"
    assert env["NEW"] == "x"


def test_merge_env_passthrough_without_overrides(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    env = merge_env(None)
    assert env["PATH"] == "/usr/bin"
