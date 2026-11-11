#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"

cd "$repo_root"
pnpm install --frozen-lockfile --prefer-offline

cd "$repo_root/web/console"
pnpm exec playwright install chromium

pnpm run generate
pnpm run lint
pnpm run typecheck
pnpm run test:unit
pnpm run test:e2e
