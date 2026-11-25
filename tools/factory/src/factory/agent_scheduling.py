"""factory-agent must not schedule work that outlives the factory's cleanup (#231).

After every step the factory kills every factory-agent process. A crontab, an
``at`` job or a lingering systemd user manager would start agent code later,
outside that cleanup. The factory user cannot read other users' crontabs or the
``at`` queue, so the preflight checks what makes them impossible: the allow and
deny lists, the linger marker and a running user manager. Existing jobs are
removed once, by the owner, in the migration step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .shell import RunCommand, run_command

# "verify agent scheduling: " plus the message must fit a Telegram abort line.
_MESSAGE_LIMIT = 300 - len("verify agent scheduling: ")


class SchedulingError(RuntimeError):
    """factory-agent could schedule work past the cleanup, or the check cannot tell."""


@dataclass(frozen=True)
class SchedulingPaths:
    cron_allow: Path = Path("/etc/cron.allow")
    cron_deny: Path = Path("/etc/cron.deny")
    at_allow: Path = Path("/etc/at.allow")
    at_deny: Path = Path("/etc/at.deny")
    at_binary: Path = Path("/usr/bin/at")
    linger_dir: Path = Path("/var/lib/systemd/linger")


DEFAULT_PATHS = SchedulingPaths()


def verify_agent_cannot_schedule(
    agent: str, paths: SchedulingPaths = DEFAULT_PATHS, *, run: RunCommand = run_command
) -> None:
    problems = [
        problem
        for problem in (
            _cron(agent, paths),
            _at(agent, paths),
            _linger(agent, paths),
            _user_manager(agent, run),
        )
        if problem is not None
    ]
    if not problems:
        return
    first = problems[0]
    count = f" ({len(problems)} problems)" if len(problems) > 1 else ""
    message = f"{agent} can schedule work: {first}{count}"
    if len(message) > _MESSAGE_LIMIT:
        message = message[: _MESSAGE_LIMIT - len(count) - 1] + "…" + count
    raise SchedulingError(message)


def _names(path: Path, agent: str) -> set[str] | str:
    """The names a cron/at list holds, matched as cron and at match them, or the problem.

    Both compare each whole line, without trimming spaces or reading comments, so
    ``factory-agent `` or ``factory-agent\\r`` does not deny the agent. Such a line
    is reported instead of being read as a denial.
    """
    try:
        # Bytes, not text: read_text would turn a stray \r into a line break.
        text = path.read_bytes().decode(errors="replace")
    except OSError:
        return f"cannot read {path}; fix: sudo chmod 644 {path}"
    lines = text.split("\n")
    for line in lines:
        if line != agent and line.strip() == agent:
            return f"{path} has {agent} with extra spaces; fix: write it alone on its line"
    return set(lines)


def _listed_rule(agent, allow: Path, deny: Path, *, neither_allows: bool, tool: str):
    """Debian's rule: an allow list decides alone; else a deny list; else the default."""
    if allow.exists():
        names = _names(allow, agent)
        if isinstance(names, str):
            return f"{tool}: {names}"
        if agent in names:
            return f"{tool}: listed in {allow}; fix: remove it from {allow}"
        return None
    if deny.exists():
        names = _names(deny, agent)
        if isinstance(names, str):
            return f"{tool}: {names}"
        if agent not in names:
            return f"{tool}: not in {deny}; fix: echo {agent} >> {deny} (as root)"
        return None
    if neither_allows:
        return f"{tool}: no {allow.name} or {deny.name}; fix: echo {agent} >> {deny} (as root)"
    return None


def _cron(agent, paths):
    # With neither file, Debian's cron lets every user have a crontab.
    return _listed_rule(agent, paths.cron_allow, paths.cron_deny, neither_allows=True, tool="cron")


def _at(agent, paths):
    if not paths.at_binary.exists():
        return None
    # With neither file, only root may use at.
    return _listed_rule(agent, paths.at_allow, paths.at_deny, neither_allows=False, tool="at")


def _linger(agent, paths):
    if (paths.linger_dir / agent).exists():
        return f"lingering is on; fix: sudo loginctl disable-linger {agent}"
    return None


def _user_manager(agent, run):
    result = run(["/usr/bin/pgrep", "-u", agent, "-x", "systemd"], "/", timeout=30)
    if result.exit_code == 0:
        return f"a systemd user manager is running; fix: sudo loginctl terminate-user {agent}"
    if result.exit_code != 1:
        reason = result.stderr.strip() or f"exit {result.exit_code}"
        return f"cannot tell whether a user manager runs (pgrep: {reason})"
    return None
