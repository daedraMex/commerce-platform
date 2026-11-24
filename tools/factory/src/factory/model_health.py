"""What the factory remembers about its models between runs (#202).

On 2026-11-19 the reviewer model had no provider login: OpenCode printed nothing,
and every factory PR said only "automated review failed" for five days. The
preflight now asks each configured model for a short answer, at most once a day
per model (``ModelChecks``), and the factory counts reviewer failures in a row
(``ReviewerFailures``) so a second one in a row reaches Telegram.

Both files live in the factory's state directory, which the agent cannot read.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

MODEL_CHECKS_FILE = "model-checks.json"
REVIEWER_FAILURES_FILE = "reviewer-failures.json"
MODEL_CHECK_MAX_AGE_SECONDS = 24 * 60 * 60
# The second failure in a row alerts: one can be a provider hiccup, two is a pattern.
REVIEWER_FAILURE_ALERT_AT = 2


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(state_dir: Path, path: Path, data: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True)
    os.replace(tmp, path)


class ModelChecks:
    """When each model last answered the preflight's model check."""

    def __init__(self, state_dir: Path, *, clock: Callable[[], float] = time.time):
        self.state_dir = state_dir
        self.path = state_dir / MODEL_CHECKS_FILE
        self._clock = clock

    def due(self, model: str) -> bool:
        last = _read_json(self.path).get(model)
        if not isinstance(last, (int, float)):
            return True
        return self._clock() - last >= MODEL_CHECK_MAX_AGE_SECONDS

    def passed(self, model: str) -> None:
        data = _read_json(self.path)
        data[model] = self._clock()
        _write_json(self.state_dir, self.path, data)


class ReviewerFailures:
    """How many pre-PR reviews in a row failed to produce a result."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / REVIEWER_FAILURES_FILE

    def failed(self) -> int:
        count = _read_json(self.path).get("in_a_row", 0)
        count = (count if isinstance(count, int) else 0) + 1
        _write_json(self.state_dir, self.path, {"in_a_row": count})
        return count

    def succeeded(self) -> None:
        if self.path.exists():
            _write_json(self.state_dir, self.path, {"in_a_row": 0})
