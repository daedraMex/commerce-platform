#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pnpm run generate
pnpm run lint
pnpm run typecheck
pnpm run test:unit
pnpm run test:e2e
