"""Verify sudo does not log the factory's successful downgrade commands.

sudo writes every allowed command — including the environment named in
``--preserve-env`` and the prompt passed to OpenCode — to the journal. The
factory therefore requires ``Defaults:factory !log_allowed``: successful
commands stay out of the journal, denied commands are still logged. The
preflight checks the *effective* policy with ``sudo -n -l`` (no password is
needed because the rules are NOPASSWD) so the setting cannot silently regress.
"""

from __future__ import annotations

import re

from .shell import CommandResult, RunCommand, run_command

REQUIRED_FLAG = "!log_allowed"
DEFAULTS_HEADER = "matching defaults entries"

_TOKENS_RE = re.compile(r"[\s,]+")


class SudoersError(RuntimeError):
    """Raised when the effective sudo policy would log successful commands."""


def _matching_defaults(text: str) -> str:
    """Return the "Matching Defaults entries" block, wrapped lines included."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith(DEFAULTS_HEADER):
            section = [line]
            for following in lines[index + 1 :]:
                if not following.strip():
                    break
                section.append(following)
            return "\n".join(section)
    return ""


def has_no_log_allowed(text: str) -> bool:
    """Return whether the effective defaults contain the ``!log_allowed`` flag."""
    return REQUIRED_FLAG in _TOKENS_RE.split(_matching_defaults(text))


def verify_sudoers_logging(run: RunCommand = run_command) -> None:
    """Fail unless ``sudo -n -l`` reports ``!log_allowed`` for the factory user.

    The factory process already runs as ``factory``; ``-n`` makes a missing
    NOPASSWD rule fail fast instead of waiting for a password. Any non-zero
    exit or a listing without the flag aborts the run.
    """
    result: CommandResult = run(
        ["sudo", "-n", "-l"],
        cwd="/",
        timeout=60,
        env={"LC_ALL": "C"},
    )
    if result.exit_code != 0:
        raise SudoersError(
            "could not read the effective sudo policy with 'sudo -n -l': "
            f"{result.stderr.strip() or result.exit_code}"
        )
    if not has_no_log_allowed(result.stdout):
        raise SudoersError(
            "the effective sudo policy lacks '!log_allowed' in its Matching "
            "Defaults entries; successful commands (environment and prompt "
            "included) would be written to the journal. Add "
            "'Defaults:factory !log_allowed' to /etc/sudoers.d/factory-agent."
        )
