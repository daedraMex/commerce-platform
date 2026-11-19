#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"

cd "$repo_root"
pnpm install --frozen-lockfile --prefer-offline

cd "$repo_root/web/console"
pnpm exec playwright install chromium

pnpm run generate
# Both lint steps run before failing, so one never hides the other's findings.
lint_failed=0
pnpm run lint || lint_failed=1
node scripts/check-silencers.mjs || lint_failed=1
if [ "$lint_failed" -ne 0 ]; then
  exit 1
fi
pnpm run typecheck
pnpm run test:unit
pnpm run test:e2e
