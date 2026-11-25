"""Backend code and tests never run git (2026-11-25 factory outage).

On the factory machine the checks run as factory-agent in a worktree that the
factory user owns, and git refuses it ("dubious ownership", exit 128): a test that
shells out to git passes in CI and fails every preflight. Walk files instead.
"""

import ast

from tests.architecture.support import BACKEND_DIR, parse, relative

_RUNNERS = {"run", "check_output", "check_call", "call", "Popen"}


def git_calls(tree):
    """(line) for each subprocess call whose argv literal starts with "git"."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in _RUNNERS:
            continue
        argv = node.args[0]
        if isinstance(argv, ast.List | ast.Tuple) and argv.elts:
            first = argv.elts[0]
            if isinstance(first, ast.Constant) and str(first.value).split("/")[-1] == "git":
                found.append(node.lineno)
        elif isinstance(argv, ast.Constant) and str(argv.value).split()[0:1] == ["git"]:
            found.append(node.lineno)
    return found


def _sources():
    roots = (BACKEND_DIR / "apps", BACKEND_DIR / "tests", BACKEND_DIR / "config")
    return sorted(path for root in roots for path in root.rglob("*.py"))


def test_no_backend_code_or_test_runs_git():
    calls = [f"{relative(path)}:{line}" for path in _sources() for line in git_calls(parse(path))]

    assert calls == [], "Walk the files instead of running git (it fails on the factory machine)."


def test_the_guard_finds_every_form():
    tree = ast.parse(
        "subprocess.run(['git', 'ls-files'])\n"
        "subprocess.check_output(('/usr/bin/git', 'status'))\n"
        "run('git ls-files', shell=True)\n"
        "subprocess.run(['uv', 'run', 'ruff'])\n"
    )

    assert git_calls(tree) == [1, 2, 3]
