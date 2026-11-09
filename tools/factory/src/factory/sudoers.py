"""Verify sudo does not log the factory's successful downgrade commands.

sudo writes every allowed command — including the environment named in
``--preserve-env`` and the prompt passed to OpenCode — to the journal. The
factory therefore requires ``Defaults:factory !log_allowed`` in its sudoers
drop-in: successful commands stay out of the journal, denied commands are still
logged. The preflight checks this line so the setting cannot silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

SUDOERS_PATH = Path("/etc/sudoers.d/factory-agent")
REQUIRED_LINE = "Defaults:factory !log_allowed"

_REQUIRED_RE = re.compile(r"^Defaults\s*:\s*factory\s+!log_allowed$")


class SudoersError(RuntimeError):
    """Raised when the sudoers drop-in would log successful command details."""


def _directives(text: str) -> list[str]:
    """Return the live sudoers lines, dropping comments and blank lines."""
    lines: list[str] = []
    for line in text.splitlines():
        directive = line.split("#", 1)[0].strip()
        if directive:
            lines.append(directive)
    return lines


def has_no_log_allowed(text: str) -> bool:
    """Return whether ``text`` sets ``!log_allowed`` for the factory user."""
    return any(_REQUIRED_RE.match(line) for line in _directives(text))


def verify_sudoers_logging(path: Path = SUDOERS_PATH) -> None:
    """Fail unless the sudoers drop-in contains the no-logging default.

    The file must be readable by the factory user (for example ``root:factory``
    mode ``0440``); otherwise this check fails closed and the run stops.
    """
    try:
        text = path.read_text()
    except OSError as exc:
        raise SudoersError(
            f"cannot read {path}: {exc}. Make it readable by the factory user "
            f"(root:factory, mode 0440) and add '{REQUIRED_LINE}'."
        ) from exc
    if not has_no_log_allowed(text):
        raise SudoersError(
            f"{path} must contain '{REQUIRED_LINE}' so successful sudo commands "
            "(environment and prompt included) are not written to the journal."
        )
