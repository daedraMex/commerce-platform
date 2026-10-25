from pathlib import Path
from urllib.parse import urlparse

import pytest

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def validate_service_urls(path: Path) -> None:
    env = read_env_file(path)

    database = urlparse(env["DATABASE_URL"])
    if database.scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"DATABASE_URL must use postgres/postgresql, got {database.scheme!r}")
    if not database.hostname or not database.path.strip("/"):
        raise ValueError("DATABASE_URL must include a host and a database name")

    redis = urlparse(env["REDIS_URL"])
    if redis.scheme != "redis":
        raise ValueError(f"REDIS_URL must use redis://, got {redis.scheme!r}")


def test_env_example_uses_postgres_and_redis_urls():
    validate_service_urls(ENV_EXAMPLE)


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
def test_env_example_checker_rejects_invalid_urls(tmp_path, variable, value):
    env = read_env_file(ENV_EXAMPLE)
    env[variable] = value
    broken = tmp_path / ".env.example"
    broken.write_text("\n".join(f"{key}={val}" for key, val in env.items()), encoding="utf-8")

    with pytest.raises(ValueError, match=f"{variable} must"):
        validate_service_urls(broken)
