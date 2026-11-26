---
status: accepted
---

# Build one immutable image per app and promote it by digest

A release builds the backend image and the Quetzal image once, on every green
merge to `main`, and pushes them to GHCR tagged with the commit SHA. Staging
runs that SHA image. A `vX.Y.Z` tag that points at an already-built commit
retags the exact same digest for production; production never rebuilds. This
guarantees production runs the bytes staging tested and removes a class of
"works in staging, fails in production" differences.

Migrations run in one `migrate` step before api, worker and beat start, never in
each worker's boot. They are forward-only and expand–contract: a migration is
additive and backward-compatible for at least one release, and a destructive
change ships only after no code uses the old form. Rolling back means deploying
the previous image digest, which still works on the newer schema; a bad
migration is fixed forward with a new tag, never by reverting the schema.

## Considered Options

- Rebuild on every tag: rejected. It can produce a different binary than the one
  staging tested and hides differences until production.
- Run `migrate` in the api entrypoint only: rejected. api, worker and beat share
  one image with different commands, so a boot-time migration races between
  containers and hides ordering.

## Consequences

- The pipeline is health-gated: if `/api/v1/health/ready/` fails after deploy,
  it rolls back to the previous digest and alerts Telegram.
- A migration that is not backward-compatible cannot ship in the same release
  that uses it; the expand and contract halves are separate releases.
- `APP_VERSION` carries the tag/SHA so the liveness endpoint reports what is
  running; `:staging` and `:prod` are moving aliases and only the digest is
  immutable.
