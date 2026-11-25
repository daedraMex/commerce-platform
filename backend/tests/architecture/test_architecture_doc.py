"""docs/architecture.md names only files and folders that exist (#148).

The map is read by agents, so a path that moved or was deleted would mislead them.
Paths of planned parts (the storefront, the mobile app) are listed as planned.
"""

import re

from tests.architecture.support import BACKEND_DIR

REPO_DIR = BACKEND_DIR.parent
DOC = REPO_DIR / "docs" / "architecture.md"
PLANNED = ("web/storefront/", "mobile/")
# Backticked text that looks like a path: has a slash or a file extension.
_PATH = re.compile(r"`([A-Za-z0-9_.\[\]/-]+(?:/|\.(?:py|md|ts|tsx|json|toml|sh)))`")
# Relative to the module or folder the sentence is about.
_BASES = (
    "",
    "backend/",
    "backend/apps/photos/",
    "backend/tests/architecture/",
    "web/console/",
    "tools/factory/src/factory/",
)


def _exists(path):
    path = path.removeprefix("/")
    return any((REPO_DIR / base / path).exists() for base in _BASES)


def doc_paths(text):
    return sorted({match.group(1) for match in _PATH.finditer(text)})


def test_every_path_in_the_architecture_map_exists():
    missing = [
        path
        for path in doc_paths(DOC.read_text())
        if not path.startswith(PLANNED) and not path.startswith("/api/") and not _exists(path)
    ]

    assert missing == [], "docs/architecture.md names paths that do not exist"


def test_the_path_pattern_finds_files_and_folders():
    assert doc_paths(
        "see `apps/photos/interfaces/tasks.py` and `web/console/` but not `X-Store`"
    ) == [
        "apps/photos/interfaces/tasks.py",
        "web/console/",
    ]


def test_a_moved_path_is_reported():
    assert _exists("apps/photos/interfaces/tasks.py")
    assert not _exists("apps/photos/interfaces/jobs.py")
