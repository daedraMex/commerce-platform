# commerce-platform

Monorepo for a multi-store e-commerce platform. One backend serves any number of
stores (today `anime`: anime merchandise such as caps, t-shirts and other anime products;
`kawaii`: kawaii stationery such as BTS holders, lomo cards, notebooks, stickers, pens and
squishies; `llaveros`: keychains of every kind, retail and wholesale for resellers; and
`home`: blankets), a single themed storefront, a future mobile app, and a platform of AI
agents (Instagram publishing, WhatsApp sales, customer follow-up, bundle suggestions).

It runs for one business today and will become a SaaS later. New optional features are
enabled for our own stores first (feature flags) and rolled out to others after.

Read GLOSSARY.md for the domain vocabulary, ROADMAP.md for phases and the
Definition of Done, and docs/adr/ for the decisions already taken.
Read docs/architecture.md when a ticket touches more than one module, adds a module,
or crosses areas (backend, console, factory): it maps the code and names the ADR that
rules each part.

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
- A ticket's **Contracts** section names sections of docs/contracts/<module>.md (ADR-0031):
  read them before /implement, and update them in the same pull request when the
  contract changes.
- Pin every GitHub Actions dependency to a commit SHA after verifying the tagged
  version exists.
- Commit before /code-review, because it diffs `main...HEAD`.
- Every pull request review, by an agent or with /code-review, applies REVIEW.md as read
  from `main`.
- An agent's mistake becomes a guard (lint rule, architecture check or test) in a
  protected path; /retro decides the rare exception that becomes an instruction.
- Before rewording a phrase in the docs, search the whole repo for it and change
  every copy at once.
- The backend has no typechecker: for backend work, skip /implement's typechecking step
  and run `backend/scripts/check.sh` instead. The console is typechecked by
  `web/console/scripts/check.sh`.

## Stack
- backend/: Python 3.12 managed with uv, Django 5.2 LTS, Django REST Framework, Celery, PostgreSQL 16, Redis 7
- web/storefront/: one Next.js + TypeScript app; the store and its theme are resolved by domain (later)
- mobile/: Kotlin Multiplatform + Compose Multiplatform, Material 3 (later, ADR-0029)
- packages/api-client/: TypeScript client generated from the OpenAPI schema
- Deploy: backend on a VPS with Dokploy, storefront on Vercel
- Tickets: GitHub Issues

## Conventions
- All code in English: variables, functions, classes, files, database names,
  comments, error messages and commit messages.
- Modular monolith. Each Django app in backend/apps/ is a module.
- Modules with business rules (inventory, orders, payments, shipping, photos, agents)
  follow clean architecture:
  - domain/: pure Python, no Django, DRF or infrastructure imports
  - application/: one use case per file, dependencies injected as ports
  - infrastructure/: Django ORM, repositories, external gateways
  - interfaces/: DRF views and serializers, Celery tasks
- CRUD-only modules (accounts, stores, catalog) use plain Django.
- Other modules use the catalog only through `apps.catalog.services`, `apps.catalog.rules`
  and the media URL builders `media_url` and `rendition_url` (ADR-0005).
- Modules talk to each other only through services or ports; never write another
  module's models directly.
- DRF is a thin layer: serializers validate shape, use cases enforce rules.
  No ModelViewSet or ModelSerializer.save() in modules with business rules.
- Authorization for important actions is enforced inside use cases through the
  Authorizer port, not only in views.
- Never delete products or orders; use is_active or status. Variants are deactivated,
  never deleted.
- A SKU never changes once created: it is printed on product labels. A product never
  changes its store or its category.
- A product label's QR code encodes the label link https://q.berlekgroup.com/<store>/<SKU>
  and never the product page URL; the platform redirects it (ADR-0035). That link format
  never changes.
- External providers (payments, shipping) sit behind a port, and the domain uses our own
  terms, never the provider's identifiers or formats; a record keeps the provider's id only
  as an external reference with the provider name. Which provider a store uses is a
  per-store setting (ADR-0034).
- Every API error is an RFC 9457 problem details response with a stable `code`.
- OpenAPI examples are fixed literal values, never read from settings or the
  environment, so the generated schema is deterministic.
- The media bucket holds public product media only; never store private files
  (invoices, customer documents) in it.
- A catalog image is our own photo or an image its supplier authorized in writing
  (ADR-0033); it never shows a watermark.

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
- docker compose up -d                      # PostgreSQL, Redis, RustFS buckets and the worker
- cd backend && uv sync                     # Python dependencies from uv.lock
- uv run python manage.py runserver
- cd backend && ./scripts/check.sh           # everything CI runs: ruff, import-linter, migrations, schema, pytest
- cd backend && uv run ruff format .         # fix formatting
- cd backend && uv run pytest tests/api/test_health.py   # one test file while iterating
- cd backend && uv run pytest tests/broker -m real_broker   # a task through Redis and a real worker; skipped by default
- cd backend && uv run pre-commit install --config ../.pre-commit-config.yaml
  # installs the ruff hooks that run on every commit
- pnpm install                              # Node dependencies (Node from .nvmrc)
- pnpm dev:console                          # Quetzal at http://localhost:3000/<store>
- ./web/console/scripts/check.sh            # generate client, lint, typecheck, unit, level-1 tests
- docker compose up -d postgres redis rustfs storage-init   # level-2 dependencies; run the host commands from docs/factory.md
- cd backend && DEBUG=True E2E_SEED_ALLOWED=1 E2E_STAFF_EMAIL=e2e@example.com E2E_STAFF_PASSWORD=local-e2e uv run python manage.py e2e_seed
- pnpm --filter @commerce-platform/console test:e2e:level2   # level-2 Playwright against the running stack
- pnpm generate:client                      # regenerate packages/api-client from openapi.json
- cd backend && uv run python manage.py dump_openapi   # refresh packages/api-client/openapi.json
- cd backend && uv run python manage.py flushexpiredtokens   # purge expired JWT blacklist rows

## Testing
- Write the failing test first.
- Use cases: unit tests with fake ports, no database, in backend/tests/unit/.
- Endpoints: API tests end to end, in backend/tests/api/.
- Models, managers, admin and management commands: integration tests that use the
  database or Django machinery but do not go through an endpoint, in
  backend/tests/integration/.
- Architecture guards (layering, allowed imports between modules): AST tests in
  backend/tests/architecture/, a protected path.
- Celery tasks end to end through a real Redis broker and worker: backend/tests/broker/,
  marked `real_broker`, which the default run skips and CI runs in its own job.
- Store-scoped features need a test proving one store's data never appears in another.

## Safety
- For factory pull requests, the owner's GitHub approval is the only gate to
  `main`. Agents — the night factory, evaluators and reviewers — never approve a
  pull request. The factory may enable auto-merge with merge commits but never
  approves or merges directly. As repository admin the owner may bypass the
  approval ruleset only to merge her own human pull requests, which GitHub does
  not let her approve; the required checks have no bypass (ADR-0032).
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