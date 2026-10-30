#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file /dev/null
uv run pytest
