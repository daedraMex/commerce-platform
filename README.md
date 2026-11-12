# commerce-platform

Multi-store e-commerce platform: one Django backend for any number of stores,
a themed Next.js storefront, a mobile app and a platform of AI agents.

- Project instructions for coding agents: [AGENTS.md](AGENTS.md)
- Phases, Definition of Ready and Definition of Done: [ROADMAP.md](ROADMAP.md)
- Prompts for each phase: [phase-prompts.md](phase-prompts.md)

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker Desktop
- OpenCode with a DeepSeek API key (for AI-assisted development)

## Getting started

```bash
# 1. Start PostgreSQL, Redis, RustFS (public and private buckets) and the Celery worker
docker compose up -d

# 2. Install backend dependencies (from uv.lock)
cd backend
uv sync

# 3. Configure the backend
cp .env.example .env    # then set SECRET_KEY

# 4. Create the database tables and your admin user
uv run python manage.py migrate
uv run python manage.py createsuperuser   # asks for your email

# 5. Run the server and open http://localhost:8000/admin/
uv run python manage.py runserver
```

Run the tests with `uv run pytest` from `backend/` (PostgreSQL must be running).

If ports 5432 or 6379 are already taken on your machine, override them:
`POSTGRES_PORT=5433 REDIS_PORT=6380 docker compose up -d` and update
`DATABASE_URL` in `backend/.env` to match.

After changing backend code, rebuild the worker so it picks up the changes:
`docker compose up -d --build worker`.

### Local media (RustFS)

`docker compose up -d` starts RustFS and a one-shot `storage-init` service that
creates the public and private buckets with the AWS CLI. The public bucket gets
an anonymous `s3:GetObject` bucket policy; the private bucket gets none. To
point the backend at it, use the RustFS values shown in `backend/.env.example`:

```bash
docker compose up -d rustfs storage-init
cd backend
R2_BUCKET_NAME=catalog-media R2_PRIVATE_BUCKET_NAME=catalog-private \
  R2_ACCESS_KEY_ID=rustfsadmin R2_SECRET_ACCESS_KEY=rustfsadmin \
  R2_ENDPOINT_URL=http://localhost:9000 \
  MEDIA_BASE_URL=http://localhost:9000/catalog-media \
  uv run python manage.py runserver
```

Without those variables the backend keeps using local files and stores private
photos under `backend/private-media/`, which is git-ignored and never served by
a URL.

## Console (Quetzal)

The staff console lives in `web/console/` and is part of a pnpm workspace at the
repo root, together with the generated API client in `packages/api-client/`.
Node comes from `.nvmrc` and pnpm from the root `packageManager` field.

```bash
pnpm install                 # install the whole workspace
pnpm dev:console             # Quetzal at http://localhost:3000/<store>
./web/console/scripts/check.sh   # generate, lint, typecheck, unit and level-1 tests
```

### API client

`packages/api-client` is generated with orval from
`packages/api-client/openapi.json`: TanStack Query hooks over one axios instance
that always sends `X-Requested-With`. The generated code is not committed; the
console's `dev`, `build` and `check` run the generation first.

```bash
pnpm generate:client         # regenerate from the committed openapi.json
pnpm --filter @commerce-platform/api-client build   # typecheck the generated client
cd backend && uv run python manage.py dump_openapi   # refresh openapi.json after API changes
cd backend && uv run python manage.py dump_openapi --check   # fail on drift
```

`backend/scripts/check.sh` runs the drift check, so a change to the API must be
accompanied by a regenerated and committed `openapi.json`. Breaking API changes
are recorded in [docs/api-changes.md](docs/api-changes.md).

## Deploying

The private photo bucket is platform infrastructure, not a per-store
credential. Set `R2_PRIVATE_BUCKET_NAME` whenever `R2_BUCKET_NAME` is set; the
two names must differ. The private bucket needs no public URL or anonymous
access, and its contents are never served under `MEDIA_BASE_URL`.

After deploying a change that adds rendition sizes or bumps
`MEDIA_RENDITION_VERSION` (including the first deploy of renditions, when
existing Media have none yet), create the missing renditions for every store:

```bash
uv run python manage.py regenerate_renditions --store <slug>
```

The command only writes missing keys and never rewrites an existing rendition,
so it is safe to run again. To change how renditions are encoded, bump
`MEDIA_RENDITION_VERSION` so they get new keys instead of overwriting cached
objects.

Refresh tokens rotate and every used or signed-out one is blacklisted
(ADR-0027), so the blacklist tables grow with each refresh. Purge the rows of
tokens that have already expired:

```bash
uv run python manage.py flushexpiredtokens
```

It is safe to run at any time. Phase 6 schedules it with Celery Beat.

## Layout

- `backend/`: Django project (`config/`) and its modules (`apps/`), managed with uv
- `web/console/`: Quetzal, the staff console (Next.js App Router)
- `packages/api-client/`: the generated API client used by the console
- `docker-compose.yml`: PostgreSQL 16, Redis 7, RustFS, the bucket initializer and the Celery worker for local development
