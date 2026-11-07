"""Resolve user-supplied child paths without letting them escape a root."""

from pathlib import Path


def safe_child_path(root, name):
    """Return the resolved path for ``name`` under ``root``.

    Absolute paths, ``..`` segments and symlinks that resolve outside ``root``
    are rejected. The caller decides whether a missing file is an error.
    """
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{name!r} is outside {root}")
    base = Path(root).resolve()
    path = (base / candidate).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"{name!r} is outside {root}") from error
    return path
