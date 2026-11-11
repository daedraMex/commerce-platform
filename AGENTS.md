# commerce-platform

Monorepo for a multi-store e-commerce platform. One backend serves any number of
stores (today `anime`: anime merchandise, `kawaii`: kawaii stationery, and `home`: blankets), a single
themed storefront, a future mobile app, and a platform of AI agents (Instagram
publishing, WhatsApp sales, customer follow-up, bundle suggestions).

It runs for one business today and will become a SaaS later. New optional features are
enabled for our own stores first (feature flags) and rolled out to others after.

Read GLOSSARY.md for the domain vocabulary, ROADMAP.md for phases and the
Definition of Done, and docs/adr/ for the decisions already taken.

## Development workflow
- This project uses the Matt Pocock skills workflow (skills in .agents/skills):
  /grill-with-docs -> /to-spec -> /to-tickets -> /implement -> /code-review -> /retro.
- Do not start Gentle-AI SDD or ODD flows here, and do not create their artifacts
  (openspec/, odd/, feature documents). Specs and tickets come from /to-spec and
  /to-tickets, tracked in GitHub Issues.
- Decisions go to docs/adr/ and vocabulary to GLOSSARY.md, not only to agent memory.
- Before /implement, check the ticket's blocking edges; if any blocker is open, stop and
  report. Never stack branches.
- When /implement invokes TDD, the ticket's acceptance criteria are the agreed seams.
- Pin every GitHub Actions dependency to a commit SHA after verifying the tagged
  version exists.
- Commit before /code-review, because it diffs `main...HEAD`.
- Before rewording a phrase in the docs, search the whole repo for it and change
  every copy at once.
- There is no typechecker in this repo: skip /implement's typechecking step and run
  `./scripts/check.sh` instead.

## Stack
- backend/: Python 3.12 managed with uv, Django 5.2 LTS, Django REST Framework, Celery, PostgreSQL 16, Redis 7
- web/storefront/: one Next.js + TypeScript app; the store and its theme are resolved by domain (later)
- mobile/: React Native + Expo (later)
- packages/api-client/: TypeScript client generated from the OpenAPI schema (later)
- Deploy: backend on a VPS with Dokploy, storefront on Vercel
- Tickets: GitHub Issues

## Conventions
- All code in English: variables, functions, classes, files, database names,
  comments, error messages and commit messages.
- Modular monolith. Each Django app in backend/apps/ is a module.
- Modules with business rules (inventory, orders, payments, photos, agents) follow clean
  architecture:
  - domain/: pure Python, no Django, DRF or infrastructure imports
  - application/: one use case per file, dependencies injected as ports
  - infrastructure/: Django ORM, repositories, external gateways
  - interfaces/: DRF views and serializers, Celery tasks
- CRUD-only modules (accounts, stores, catalog) use plain Django.
- Modules talk to each other only through services or ports; never write another
  module's models directly.
- DRF is a thin layer: serializers validate shape, use cases enforce rules.
  No ModelViewSet or ModelSerializer.save() in modules with business rules.
- Authorization for important actions is enforced inside use cases through the
  Authorizer port, not only in views.
- Never delete products or orders; use is_active or status.
- Every API error is an RFC 9457 problem details response with a stable `code`.
- OpenAPI examples are fixed literal values, never read from settings or the
  environment, so the generated schema is deterministic.
- The media bucket holds public product media only; never store private files
  (invoices, customer documents) in it.
- Never upload a supplier's watermarked image; every catalog image is our own photo.

## Stores (one business today, SaaS later)
- Never hardcode store names; stores are data, created with the `create_store` command.
- Every business table belongs to a Store, directly or through its parent.
- Endpoints are global by default; store-scoped endpoints opt in, and only they require
  the X-Store header (missing or unknown store returns 400).
- Every store-scoped query filters by request.store (resolved from the X-Store header).
- Every Celery task receives the store explicitly; never fall back to a default store.
- Integration credentials are per store, never global environment variables; they are
  encrypted in the database and read only through the CredentialStore port (ADR-0020).
- Store actions are authorized only through the Authorizer port; never use
  user.has_perm() or Django's auth.Permission for them (those only gate the admin).
- New optional features ship behind a per-store feature flag; core modules (catalog,
  inventory, orders) do not.
- Inventory is per store and always addressed by Location (StockItem = variant + location).

## Commands
- docker compose up -d                      # PostgreSQL and Redis
- cd backend && uv sync                     # Python dependencies from uv.lock
- uv run python manage.py runserver
- cd backend && ./scripts/check.sh           # everything CI runs: ruff, migrations, schema, pytest
- cd backend && uv run ruff format .         # fix formatting
- cd backend && uv run pytest tests/api/test_health.py   # one test file while iterating
- cd backend && uv run pre-commit install --config ../.pre-commit-config.yaml
  # installs the ruff hooks that run on every commit
- pnpm install                              # Node dependencies (Node from .nvmrc)
- pnpm dev:console                          # Quetzal at http://localhost:3000/<store>
- ./web/console/scripts/check.sh            # generate client, lint, typecheck, unit, level-1 tests
- pnpm generate:client                      # regenerate packages/api-client from openapi.json
- cd backend && uv run python manage.py dump_openapi   # refresh packages/api-client/openapi.json

## Testing
- Write the failing test first.
- Use cases: unit tests with fake ports, no database, in backend/tests/unit/.
- Endpoints: API tests end to end, in backend/tests/api/.
- Models, managers, admin and management commands: integration tests that use the
  database or Django machinery but do not go through an endpoint, in
  backend/tests/integration/.
- Store-scoped features need a test proving one store's data never appears in another.

## Safety
- Never read, print or commit .env files, secrets, tokens or credentials.
- Never run git push, destructive git commands or database drops without asking.
  Exception (night factory only, see ADR): may run `git push origin nf/<ticket-id>`
  to its own ticket branch. Never push to main or any other branch, never use
  --force or --force-with-lease, never delete remote branches.
- Migrations are reviewed by a human before merging.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `daedraMex/commerce-platform`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.