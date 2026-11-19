#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# The factory runs the pre-PR reviewer's attack tests through this mode, because
# check.sh is the only backend command the agent user may run. Only the
# reviewer's own files are accepted, so the mode cannot run anything else.
if [ "${1:-}" = "--review-tests" ]; then
  shift
  if [ "$#" -eq 0 ]; then
    echo "check.sh --review-tests: no test files given" >&2
    exit 2
  fi
  for file in "$@"; do
    case "$file" in
      tests/review/test_review_*.py) ;;
      *) echo "check.sh --review-tests: refusing $file" >&2; exit 2 ;;
    esac
    case "$file" in
      *..* | */./* | *//*) echo "check.sh --review-tests: refusing $file" >&2; exit 2 ;;
    esac
  done
  exec uv run pytest -p no:cacheprovider -q "$@"
fi

uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file /dev/null
uv run python manage.py dump_openapi --check
uv run pytest
