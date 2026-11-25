"""docs/architecture.md names only things that exist (#148).

The map is read by agents, so a moved file, a renumbered ADR or a renamed CI job would
mislead them. Checked: every backticked path, every cited ADR and every CI job in the
checks table. Planned parts (the storefront, the mobile app) are not checked.
"""

import re
import subprocess

from tests.architecture.support import BACKEND_DIR

REPO_DIR = BACKEND_DIR.parent
DOC = REPO_DIR / "docs" / "architecture.md"
CI = REPO_DIR / ".github" / "workflows" / "ci.yml"
PLANNED = ("web/storefront/", "mobile/")
# Names the doc uses for a role every module has, not for one file.
GENERIC = {"models.py", "admin.py", "domain/", "application/", "infrastructure/", "interfaces/"}
# Backticked text that looks like a path: has a slash or a file extension.
_PATH = re.compile(
    r"`([A-Za-z0-9_.\[\]/<>-]+(?:/|\.(?:py|md|ts|tsx|json|toml|sh|yml|yaml|mjs|js)))`"
)
# A path with a slash is written from the repo root, backend/ or web/console/.
_BASES = ("", "backend/", "web/console/")
_ADR = re.compile(r"ADR-(\d{4})")
_CI_ROW = re.compile(r"^\| ([A-Z][A-Za-z0-9 ]+?) \| `", re.MULTILINE)


def _tracked_names():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_DIR, capture_output=True, text=True, check=True
    ).stdout
    names = {}
    for line in out.splitlines():
        name = line.rsplit("/", 1)[-1]
        names[name] = names.get(name, 0) + 1
    return names


def path_problem(path, tracked_names):
    """Why ``path`` in the doc does not name exactly one existing thing, or None."""
    if "<" in path:
        path = path.split("<", 1)[0]  # a pattern such as docs/contracts/<module>.md
    if "/" not in path.rstrip("/"):
        if path.endswith("/"):
            return None if any((REPO_DIR / b / path).is_dir() for b in _BASES) else "missing"
        count = tracked_names.get(path, 0)
        return None if count == 1 else ("missing" if count == 0 else "ambiguous bare name")
    return None if any((REPO_DIR / base / path).exists() for base in _BASES) else "missing"


def doc_paths(text):
    return sorted({match.group(1) for match in _PATH.finditer(text)})


def test_every_path_in_the_architecture_map_exists_once():
    names = _tracked_names()
    problems = [
        f"{path}: {problem}"
        for path in doc_paths(DOC.read_text())
        if not path.startswith(PLANNED) and not path.startswith("/api/") and path not in GENERIC
        for problem in [path_problem(path, names)]
        if problem
    ]

    assert problems == [], "docs/architecture.md names paths that do not exist"


def test_every_cited_adr_exists():
    adrs = {path.name[:4] for path in (REPO_DIR / "docs" / "adr").glob("[0-9]*.md")}

    missing = sorted(set(_ADR.findall(DOC.read_text())) - adrs)

    assert missing == []


def test_every_ci_job_in_the_checks_table_runs_in_ci():
    jobs = set(re.findall(r"^    name: (.+)$", CI.read_text(), re.MULTILINE))
    checks = DOC.read_text().split("## Checks", 1)[1]

    rows = _CI_ROW.findall(checks)

    assert rows and set(rows) <= jobs, f"jobs in ci.yml: {sorted(jobs)}"


def test_the_guard_reports_a_moved_ambiguous_or_missing_path():
    names = {"publisher.py": 1, "models.py": 3}

    assert path_problem("apps/photos/interfaces/tasks.py", names) is None
    assert path_problem("apps/photos/interfaces/jobs.py", names) == "missing"
    assert path_problem("publisher.py", names) is None
    assert path_problem("models.py", names) == "ambiguous bare name"
    assert path_problem("gone.py", names) == "missing"
    assert path_problem("docs/contracts/<module>.md", names) is None


def test_the_path_pattern_finds_files_folders_and_configs():
    text = "`apps/x/tasks.py`, `web/console/`, `eslint.config.mjs`, `ci.yml`, not `X-Store`"

    assert doc_paths(text) == ["apps/x/tasks.py", "ci.yml", "eslint.config.mjs", "web/console/"]
