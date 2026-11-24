"""A fresh home for every OpenCode run, so no run loads what an earlier one wrote (#158).

OpenCode reads, at every start, files the agent can change in its own home: the
auth store (a ``wellknown`` entry makes it fetch and merge a remote config), its
database (an active org makes it fetch ``/api/config``), cached binaries (``rg``,
LSP servers) and ``~/.gitconfig`` (``core.fsmonitor``). A builder could use them
to blind the reviewer in a later run.

Each run instead gets ``<homes_dir>/<label>-<random>``, made by the factory with
only two files: the provider keys, copied from a factory-owned file after checking
every entry is a plain API key, and a gitconfig that trusts the worktrees. The
directory is setgid ``factory-work`` and group-writable, so the agent can write in
it; the agent deletes it after the run (its files can be ``0755``). Tool caches
(uv and its Pythons, pnpm, corepack, Playwright) stay shared in the agent's own
home: OpenCode never reads them, and keeping them warm keeps tickets fast.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from .shell import RunCommand, run_command

AGENT_AUTH_RELPATH = ".local/share/opencode/auth.json"
RM_BIN = "/usr/bin/rm"
HOME_MODE = 0o2770
FILE_MODE = 0o640
_API_FIELDS = {"type", "key"}
_HOME_DIRS = (".local", ".local/share", ".local/share/opencode", ".local/state", ".cache")


class RunHomeError(RuntimeError):
    pass


def validated_auth(text: str) -> str:
    """The auth store's text when every provider entry is a plain API key."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RunHomeError("agent-auth.json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RunHomeError("agent-auth.json is not a JSON object")
    if not data:
        raise RunHomeError("agent-auth.json has no provider")
    for provider, entry in data.items():
        if not isinstance(entry, dict) or entry.get("type") != "api":
            raise RunHomeError(f"agent-auth.json: {provider!r} is not an API key (only api keys)")
        extra = set(entry) - _API_FIELDS
        if extra:
            raise RunHomeError(
                f"agent-auth.json: {provider!r} has an unexpected field {sorted(extra)}"
            )
    return text


def _write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    os.fchmod(fd, FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def _mkdir(path: Path) -> None:
    path.mkdir(mode=HOME_MODE)
    os.chmod(path, HOME_MODE)  # mkdir's mode is filtered by the umask


class RunHomes:
    def __init__(
        self,
        *,
        homes_dir: Path,
        auth_file: Path,
        agent_user: str,
        worktrees_dir: Path,
        run: RunCommand = run_command,
    ):
        self.homes_dir = homes_dir
        self.auth_file = auth_file
        self.agent_user = agent_user
        self.worktrees_dir = worktrees_dir
        self._run = run

    def create(self, label: str) -> Path:
        """Make a fresh home holding only the factory's auth copy and gitconfig."""
        try:
            auth = self.auth_file.read_text()
        except FileNotFoundError as exc:
            raise RunHomeError(
                f"{self.auth_file} is missing: copy the agent's auth.json there "
                "(docs/factory.md, step 8)"
            ) from exc
        auth = validated_auth(auth)
        home = self.homes_dir / f"{label}-{secrets.token_hex(6)}"
        _mkdir(home)
        for relpath in _HOME_DIRS:
            _mkdir(home / relpath)
        _write(home / AGENT_AUTH_RELPATH, auth)
        _write(home / ".gitconfig", f"[safe]\n\tdirectory = {self.worktrees_dir}/*\n")
        return home

    def env(self, home: Path, *, shared_home: str) -> dict[str, str]:
        """Point OpenCode's stores at ``home``; keep the tool caches in ``shared_home``."""
        shared = Path(shared_home)
        return {
            "HOME": str(home),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "UV_CACHE_DIR": str(shared / ".cache" / "uv"),
            "npm_config_store_dir": str(shared / ".local" / "share" / "pnpm" / "store"),
            "PLAYWRIGHT_BROWSERS_PATH": str(shared / ".cache" / "ms-playwright"),
            # uv-managed Pythons: a .venv points into this, so it must outlive the run.
            "UV_PYTHON_INSTALL_DIR": str(shared / ".local" / "share" / "uv" / "python"),
            "COREPACK_HOME": str(shared / ".cache" / "node" / "corepack"),
        }

    def remove(self, home: Path) -> None:
        """Delete a run home as the agent, which may own ``0755`` files inside it."""
        if home.parent != self.homes_dir or home.is_symlink():
            raise RunHomeError(f"refusing to delete {home}: outside {self.homes_dir}")
        result = self._run(
            ["sudo", "-n", "-u", self.agent_user, "--", RM_BIN, "-rf", str(home)],
            "/",
            timeout=300,
        )
        if result.exit_code != 0:
            detail = " ".join((result.stderr or result.stdout).split())[:300]
            raise RunHomeError(f"could not delete run home {home}: {detail}")

    def remove_leftover(self, entry: Path) -> None:
        """Delete what a killed run, or a builder, left in the homes directory.

        The directory is group-writable, so a builder can plant a symlink or a
        file there. Those are unlinked by the factory, which owns the directory,
        and never followed; only real directories go through the agent's rm.
        """
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            self.remove(entry)

    def leftovers(self) -> list[Path]:
        """Run homes a killed run never deleted."""
        if not self.homes_dir.exists():
            return []
        return sorted(entry for entry in self.homes_dir.iterdir())
