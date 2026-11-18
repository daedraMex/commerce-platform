"""Every Celery task has an explicit name and receives its store (AGENTS.md)."""

import ast
import json
import os
import subprocess
import sys

from tests.architecture.support import BACKEND_DIR, parse, relative, source_files

# Tasks that touch no store data, each with the reason.
GLOBAL_TASKS = {"apps.health.tasks.smoke": "liveness check for the worker; reads no store data"}
STORE_PARAMETERS = {"store_id", "store"}


def _is_task_decorator(node):
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "shared_task"
    return isinstance(target, ast.Attribute) and target.attr in {"task", "shared_task"}


def tasks():
    for path in source_files(BACKEND_DIR / "apps") + source_files(BACKEND_DIR / "config"):
        for node in ast.walk(parse(path)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorator = next((d for d in node.decorator_list if _is_task_decorator(d)), None)
            if decorator is not None:
                yield relative(path), node, decorator


def _explicit_name(decorator):
    if not isinstance(decorator, ast.Call):
        return None
    for keyword in decorator.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def test_the_task_scan_finds_the_known_tasks():
    names = {_explicit_name(decorator) for _path, _node, decorator in tasks()}

    assert {"apps.photos.tasks.process_photo", "apps.health.tasks.smoke"} <= names


def test_every_task_sets_an_explicit_name():
    unnamed = [
        f"{path}:{node.name}" for path, node, decorator in tasks() if not _explicit_name(decorator)
    ]

    assert unnamed == [], "Set name= on every task; producers send it by name."


def test_every_task_receives_its_store():
    storeless = [
        f"{path}:{node.name}"
        for path, node, decorator in tasks()
        if _explicit_name(decorator) not in GLOBAL_TASKS
        and not STORE_PARAMETERS
        & {arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
    ]

    assert storeless == [], "Every task receives the store explicitly (store_id)."


def test_the_worker_registers_every_task_in_the_code():
    # A fresh process, as `celery -A config worker` starts: nothing imported by other tests.
    script = (
        "import django, json; django.setup()\n"
        "from config.celery import app\n"
        "app.loader.import_default_modules()\n"
        "print(json.dumps(sorted(app.tasks)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings"},
    )
    registered = set(json.loads(result.stdout.strip().splitlines()[-1]))
    in_code = {_explicit_name(decorator) for _path, _node, decorator in tasks()}

    assert in_code - registered == set(), "config/celery.py must discover every task module."
