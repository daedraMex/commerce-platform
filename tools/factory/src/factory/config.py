"""Factory settings, read from environment variables.

Secrets (model keys, GitHub token, Telegram token) are read from the factory
user's secrets file and never from the repo. Only the two model ids are read
here; the tokens live in the machine account's fine-grained token and the
Telegram bot token environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class FactoryConfigError(RuntimeError):
    """Raised when the factory is missing or misconfigured a required setting."""


def _read(env: dict[str, str] | None, name: str) -> str | None:
    source = os.environ if env is None else env
    value = source.get(name)
    return value if value not in (None, "") else None


def _read_int(env: dict[str, str] | None, name: str, default: int) -> int:
    raw = _read(env, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise FactoryConfigError(f"{name} must be an integer, got {raw!r}.") from exc


@dataclass(frozen=True)
class Settings:
    """Resolved factory configuration."""

    factory_model: str
    factory_strong_model: str
    repo: str
    max_tickets: int
    attempts: int
    repo_dir: Path
    worktrees_dir: Path
    logs_dir: Path
    time_limit_seconds: int
    keep_days: int
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    github_app_id: str | None
    github_private_key: str | None
    github_installation_id: str | None
    agent_user: str = "factory-agent"
    secrets_file: Path = field(default_factory=lambda: Path.home() / "factory" / "secrets.env")
    xolo_config_dir: Path = field(default_factory=lambda: Path.home() / ".config" / "xolo-bot")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        factory_model = _read(env, "FACTORY_MODEL")
        factory_strong_model = _read(env, "FACTORY_STRONG_MODEL")
        if not factory_model:
            raise FactoryConfigError(
                "FACTORY_MODEL is not set; add it to the factory user's secrets file."
            )
        if not factory_strong_model:
            raise FactoryConfigError(
                "FACTORY_STRONG_MODEL is not set; add it to the factory user's secrets file."
            )
        home = Path.home()
        return cls(
            factory_model=factory_model,
            factory_strong_model=factory_strong_model,
            repo=_read(env, "FACTORY_REPO") or "daedraMex/commerce-platform",
            max_tickets=_read_int(env, "FACTORY_MAX_TICKETS", 1),
            attempts=_read_int(env, "FACTORY_ATTEMPTS", 5),
            repo_dir=Path(_read(env, "FACTORY_REPO_DIR") or str(home / "factory" / "repo")),
            worktrees_dir=Path(
                _read(env, "FACTORY_WORKTREES_DIR") or str(home / "factory" / "worktrees")
            ),
            logs_dir=Path(_read(env, "FACTORY_LOGS_DIR") or str(home / "factory" / "logs")),
            time_limit_seconds=_read_int(env, "FACTORY_TIME_LIMIT_MINUTES", 120) * 60,
            keep_days=_read_int(env, "FACTORY_KEEP_DAYS", 14),
            telegram_bot_token=_read(env, "FACTORY_TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_read(env, "FACTORY_TELEGRAM_CHAT_ID"),
            github_app_id=_read(env, "XOLO_BOT_APP_ID"),
            github_private_key=_read(env, "XOLO_BOT_PRIVATE_KEY"),
            github_installation_id=_read(env, "XOLO_BOT_INSTALLATION_ID"),
            agent_user=_read(env, "FACTORY_AGENT_USER") or "factory-agent",
            secrets_file=Path(
                _read(env, "FACTORY_SECRETS_FILE") or str(home / "factory" / "secrets.env")
            ),
            xolo_config_dir=Path(
                _read(env, "XOLO_BOT_CONFIG_DIR") or str(home / ".config" / "xolo-bot")
            ),
        )
