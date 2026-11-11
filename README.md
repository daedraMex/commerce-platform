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
# 1. Start PostgreSQL, Redis and the Celery worker
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

## Layout

- `backend/`: Django project (`config/`) and its modules (`apps/`), managed with uv
- `docker-compose.yml`: PostgreSQL 16, Redis 7 and the Celery worker for local development