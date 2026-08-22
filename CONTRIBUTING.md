# Contributing to Tracely

Thanks for helping out. Issues and PRs are welcome — small, focused changes land fastest.

## Ground rules

- **Open an issue first for anything non-trivial** (new feature, behavior change, new dependency)
  so we can agree on the shape before you spend time on it. Bug fixes and docs can go straight
  to a PR.
- **Read the folder README before changing that area.** Each of `backend/`, `frontend/`,
  `sdk/`, `docs/` has one, and [`CLAUDE.md`](CLAUDE.md) lists the hard rules (layering, no SQL in
  routers, every LLM call via `provider.py`, `project_id` scoping, idempotent writes). PRs that
  break those will be sent back.
- **Keep the diff minimal.** No unrelated refactors, no speculative abstractions.

## Dev setup

```bash
make install        # uv sync --all-packages --all-extras + pnpm install
make infra-up       # clickhouse, postgres, redis, minio (docker)
make migrate && make seed
make backend        # FastAPI :8000      (separate terminals)
make workers        # Celery
make frontend       # next dev — use `cd frontend && pnpm dev -p 3001` to match Docker
make demo           # populate traces, clusters, cases, gates
```

Or the whole stack in Docker: `docker compose up -d --build --wait` → UI on :3001.

Tests need no infra and run in ~6s.

## Before you push

```bash
uv run pytest -q backend/tests sdk/tests     # what CI runs
uv run ruff check . && uv run ruff format .
cd frontend && pnpm test && pnpm build       # vitest + tsc typecheck + lint
```

- Touched dependencies? Regenerate `uv.lock` (`uv lock`) — CI runs `uv sync --frozen`.
- New backend env var? Add it to `backend/tracely/config.py` **and** the `x-app-env` anchor in
  `docker-compose.yml`.
- Postgres schema change? `cd backend && uv run alembic revision -m "…"`. ClickHouse DDL goes in
  `backend/tracely/infrastructure/clickhouse/ddl/*.up.sql`.
- Add or update a test for any behavior change. Backend tests live in `backend/tests`, SDK in
  `sdk/tests`, frontend in `frontend/app/**/__tests__`.

## Pull requests

- One concern per PR. Title in imperative mood (`feat: …`, `fix: …`, `docs: …`).
- Fill in the PR template — what changed, why, and how you verified it.
- CI must be green. A maintainer will review; expect a round or two of comments.

## Security issues

Don't open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the project's
[MIT License](LICENSE).
