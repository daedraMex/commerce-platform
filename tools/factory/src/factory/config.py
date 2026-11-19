"""Factory settings, read from environment variables.

Secrets (the Telegram bot token, and the xolo-bot GitHub App id, private key
path, installation id and bot user id) come from the factory user's secrets
file, never from the repo. The xolo-bot installation token is minted on demand
and never stored.
The model provider key is not here either: the agent holds it in its own
OpenCode auth store, so it never travels through sudo (see docs/factory.md).
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
    max_open_prs: int = 2
    max_tickets_per_day: int = 6
    github_user_id: str | None = None
    agent_user: str = "factory-agent"
    agent_home: str | None = None
    state_dir: Path = field(default_factory=lambda: Path.home() / "factory" / "state")
    secrets_file: Path = field(default_factory=lambda: Path.home() / "factory" / "secrets.env")
    deploy_key: Path = field(default_factory=lambda: Path.home() / ".ssh" / "commerce_deploy")
    handoff_host: str | None = None
    pre_pr_review: bool = False
    # Off until the machine is ready: the reviewer's attack tests run through the
    # backend check.sh --review-tests mode, which the sudoers rule already allows.
    review_tests: bool = False
    agent_config_home: Path = Path("/srv/factory/agent-config")

    def __post_init__(self) -> None:
        for name, value in (
            ("FACTORY_MAX_OPEN_PRS", self.max_open_prs),
            ("FACTORY_MAX_TICKETS_PER_DAY", self.max_tickets_per_day),
        ):
            if value < 1:
                raise FactoryConfigError(f"{name} must be at least 1, got {value}.")

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
            max_open_prs=_read_int(env, "FACTORY_MAX_OPEN_PRS", 2),
            max_tickets_per_day=_read_int(env, "FACTORY_MAX_TICKETS_PER_DAY", 6),
            attempts=_read_int(env, "FACTORY_ATTEMPTS", 3),
            pre_pr_review=_read(env, "FACTORY_PRE_PR_REVIEW") not in ("0", "false", "no"),
            review_tests=_read(env, "FACTORY_REVIEW_TESTS") in ("1", "true", "yes"),
            agent_config_home=Path(
                _read(env, "FACTORY_AGENT_CONFIG_HOME") or "/srv/factory/agent-config"
            ),
            repo_dir=Path(_read(env, "FACTORY_REPO_DIR") or "/srv/factory/repo"),
            worktrees_dir=Path(_read(env, "FACTORY_WORKTREES_DIR") or "/srv/factory/worktrees"),
            logs_dir=Path(_read(env, "FACTORY_LOGS_DIR") or str(home / "factory" / "logs")),
            state_dir=Path(_read(env, "FACTORY_STATE_DIR") or str(home / "factory" / "state")),
            time_limit_seconds=_read_int(env, "FACTORY_TIME_LIMIT_MINUTES", 120) * 60,
            keep_days=_read_int(env, "FACTORY_KEEP_DAYS", 14),
            telegram_bot_token=_read(env, "FACTORY_TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_read(env, "FACTORY_TELEGRAM_CHAT_ID"),
            github_app_id=_read(env, "XOLO_BOT_APP_ID"),
            github_private_key=_read(env, "XOLO_BOT_PRIVATE_KEY"),
            github_installation_id=_read(env, "XOLO_BOT_INSTALLATION_ID"),
            github_user_id=_read(env, "XOLO_BOT_USER_ID"),
            agent_user=_read(env, "FACTORY_AGENT_USER") or "factory-agent",
            agent_home=_read(env, "FACTORY_AGENT_HOME"),
            secrets_file=Path(
                _read(env, "FACTORY_SECRETS_FILE") or str(home / "factory" / "secrets.env")
            ),
            deploy_key=Path(
                _read(env, "FACTORY_DEPLOY_KEY") or str(home / ".ssh" / "commerce_deploy")
            ),
            handoff_host=_read(env, "FACTORY_HOST"),
        )
