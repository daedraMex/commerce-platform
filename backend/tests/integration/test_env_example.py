from pathlib import Path

import environ
import pytest

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
ROOT_GITIGNORE = Path(__file__).resolve().parents[3] / ".gitignore"

VALID_ENV = {
    "DATABASE_URL": "postgres://shop:shop@localhost:5432/shop",
    "REDIS_URL": "redis://localhost:6379/0",
}


@pytest.fixture
def load_env(monkeypatch):
    def load(path: Path) -> environ.Env:
        monkeypatch.setattr(environ.Env, "ENVIRON", {})
        environ.Env.read_env(path, overwrite=True)
        return environ.Env()

    return load


def validate_service_urls(env: environ.Env) -> None:
    database = environ.Env.db_url_config(env("DATABASE_URL"))
    if database["ENGINE"] != "django.db.backends.postgresql":
        raise ValueError(f"DATABASE_URL must use postgres/postgresql, got {database['ENGINE']!r}")
    if not database["NAME"] or not database["HOST"]:
        raise ValueError("DATABASE_URL must include a host and a database name")

    redis = env.url("REDIS_URL")
    if redis.scheme != "redis":
        raise ValueError(f"REDIS_URL must use redis://, got {redis.scheme!r}")


def test_env_example_uses_postgres_and_redis_urls(load_env):
    validate_service_urls(load_env(ENV_EXAMPLE))


def test_env_example_only_documents_the_r2_media_names():
    content = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "AWS_" not in content
    for name in (
        "R2_BUCKET_NAME",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_ENDPOINT_URL",
        "R2_REGION_NAME",
        "MEDIA_BASE_URL",
    ):
        assert name in content


def test_the_local_media_directory_is_git_ignored():
    content = ROOT_GITIGNORE.read_text(encoding="utf-8")

    assert "backend/media/" in content


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("DATABASE_URL", "mysql://shop:shop@localhost:5432/shop"),
        ("DATABASE_URL", "shop:shop@localhost:5432/shop"),
        ("DATABASE_URL", "postgres://"),
        ("REDIS_URL", "rediss://localhost:6379/0"),
        ("REDIS_URL", "http://localhost:6379/0"),
    ],
)
def test_env_example_checker_rejects_invalid_urls(load_env, tmp_path, variable, value):
    env_values = {**VALID_ENV, variable: value}
    broken = tmp_path / ".env.example"
    broken.write_text(
        "\n".join(f"{key}={val}" for key, val in env_values.items()), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=f"{variable} must"):
        validate_service_urls(load_env(broken))
