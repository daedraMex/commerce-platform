"""The areas a ticket can touch and the check script that proves each one.

The factory runs only the areas whose files changed. A ticket that changes no
known area (for example docs only) runs every area, and an area whose script is
absent from the worktree is skipped by the runner.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Area:
    """One checkable part of the monorepo."""

    name: str
    script: Path
    port: int | None = None
    # Folders the check leaves behind that explain a failure (Playwright traces, #227).
    reports: tuple[Path, ...] = ()


BACKEND = Area("backend", Path("backend") / "scripts" / "check.sh")
CONSOLE = Area(
    "console",
    Path("web") / "console" / "scripts" / "check.sh",
    port=3000,
    reports=(
        Path("web") / "console" / "test-results",
        Path("web") / "console" / "playwright-report",
    ),
)
AREAS: tuple[Area, ...] = (BACKEND, CONSOLE)


def area_for_path(path: str | Path) -> Area | None:
    """Map one changed file to the area whose check covers it."""
    parts = Path(path).parts
    if not parts:
        return None
    if parts[0] == "backend":
        return BACKEND
    if parts[0] == "packages":
        return CONSOLE
    if parts[0] == "web" and len(parts) > 1 and parts[1] == "console":
        return CONSOLE
    return None


def select_areas(paths: Iterable[str | Path]) -> tuple[Area, ...]:
    """Return the areas for these changed files, or every area when none match."""
    selected = {area.name for path in paths if (area := area_for_path(path)) is not None}
    if not selected:
        return AREAS
    return tuple(area for area in AREAS if area.name in selected)
