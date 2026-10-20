# Repository Guidelines

Platybill is a household bill-tracking PWA. Stack: Next.js 16 (App Router, TypeScript, Tailwind) frontend + FastAPI (Python 3.13) backend in a single all-in-one Docker image (Next standalone + uvicorn under supervisord), with SQLite at `/data/platybill.db` (WAL). The browser calls `/api/*` same-origin; the Next server proxies to uvicorn on `127.0.0.1:8010` inside the container. There is no Postgres service.

## Hard Rules

- **Next.js 16 has breaking changes from training data.** Before writing any frontend code, read `@frontend/AGENTS.md` — its warning is load-bearing.
- **Recurrence auto-generation is idempotent.** The key is `(bill_id, due_date)`. Never insert a `PaymentInstance` without checking for an existing row on that pair — see `@backend/app/services/recurrence.py`. (`period` stays `"YYYY-MM"` and is derived from `due_date`.)
- **Archive templates, never delete.** Set `is_archived = True` on `BillTemplate`; hard deletes cascade to payment history.
- **Migrations run automatically on container start.** `docker/entrypoint.sh` takes a pre-migration SQLite snapshot into `/data/backups`, then runs `alembic upgrade head`. New model changes need a new revision: `cd backend && uv run alembic revision --autogenerate -m "<desc>"`, hand-review it (SQLite migrations run with `render_as_batch=True`), then `upgrade head`.
- **Use SQLAlchemy 2.0 `Mapped[T]` / `mapped_column()` style.** The 1.x `Column()` pattern will pass linting but is wrong for this codebase — see `@backend/app/models/bill.py`.
- **SQLite is the only database.** Money uses the `Money` type decorator (integer cents) and timestamps use `UTCDateTime` (naive UTC storage) — see `@backend/app/core/types.py`. Avoid Postgres-only SQL in queries and keep date functions portable (`strftime`, not `to_char`).

## Project Structure

```
frontend/   Next.js 16 PWA — App Router, src/, Tailwind
backend/    FastAPI — app/{routers,models,schemas,services,core}/, alembic/, tests/
            scripts/migrate_postgres_to_sqlite.py — one-off 3.1.x Postgres → SQLite ETL
docker/     entrypoint.sh — PUID/PGID, JWT secret persistence, pre-migration backup, supervisord
templates/  Unraid Community Applications template (prepared, not yet submitted)
ca_profile.xml  Unraid CA profile (prepared, not yet submitted)
infra/      backup.sh (WAL-safe SQLite snapshot), caddy reference config
context/    10x workflow artifacts (PRD, tech-stack, roadmap, bootstrap log)
```

See `@context/foundation/prd.md` for domain rules and `@context/foundation/tech-stack.md` for stack rationale.

## Build & Development Commands

- `docker compose up --build` — whole stack as one container (UI + API on `3010`)
- `docker compose --profile demo up --build` — same, seeded with demo data (`demo@demo.com` / `demo1234`)
- `docker compose down -v && docker compose up --build` — clean start, wipes the SQLite volume
- `cd frontend && API_PREFIX=/api npm run dev` — frontend only, no Docker (the `/api` rewrite targets `127.0.0.1:8010`; without `API_PREFIX=/api` the browser-side client would call the backend path without the `/api` prefix and miss the rewrite)
- `cd backend && DATABASE_URL=sqlite:///./dev.db uv run uvicorn app.main:app --reload` — backend only, no Docker (without the override the default `/data/platybill.db` path is not writable on most dev machines)
- `cd frontend && npm run lint` — ESLint
- `cd frontend && npm run lint && npm run build` — full frontend check
- `cd backend && uv run pytest` — backend tests
- `cd backend && uv run alembic revision --autogenerate -m "<desc>"` — new migration (hand-review, then `upgrade head`)

API docs (development only): `http://localhost:3010/api/docs` via the container, or `http://localhost:8010/docs` with the split backend. Images publish to `ghcr.io/mjc668/platybill` from green `main` commits with tags `sha-<7>`, `main`, and `latest`; there are no GitHub Releases or version numbers (the footer shows the deployed commit).

## Coding Style & Conventions

- **Frontend:** No `any`. Do not add a `pages/` directory — this project is App Router only. Components in `frontend/src/`.
- **Backend:** All request/response types use Pydantic schemas in `backend/app/schemas/`. Never use raw dicts as router return types. Routers in `backend/app/routers/`, business logic in `backend/app/services/`.
- **Env vars:** copy `.env.example` → `.env`; never commit `.env`.

## Pre-commit Hooks

After cloning, install the hooks once:

```bash
pip install pre-commit
pre-commit install          # file-staged secrets scan on git commit
pre-commit install --hook-type commit-msg   # conventional-commit lint on commit message
```

Hooks defined in `.pre-commit-config.yaml`:
- `detect-secrets` — prevents accidental secret commits; baseline in `.secrets.baseline`
- `conventional-pre-commit` — enforces Conventional Commits message format

To update the secrets baseline after an intentional addition: `detect-secrets scan > .secrets.baseline`.

## Commit Guidelines

Conventional Commits prefix required: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`. One-line subject under 72 characters. Reference the PRD FR number in the body when implementing a functional requirement (e.g. `Implements FR-009`).
Finish the job: commit related changes together, push to `main`, then confirm the CI run for the pushed commit completes successfully — fix-forward on failure, never leave `main` red.
