## What

<!-- One or two sentences. Link the issue: Closes #123 -->

## Why

<!-- The problem this solves, or the user-facing behavior it changes. -->

## How verified

<!-- Tests added/updated, manual steps, screenshots for UI changes. -->

## Checklist

- [ ] `uv run pytest -q backend/tests sdk/tests` passes
- [ ] `uv run ruff check . && uv run ruff format .` clean
- [ ] `cd frontend && pnpm test && pnpm build` passes (if frontend touched)
- [ ] Follows the hard rules in `CLAUDE.md` (no SQL in routers, LLM calls via `provider.py`, `project_id` scoping)
- [ ] New env var added to `config.py` **and** `docker-compose.yml` `x-app-env` (if any)
- [ ] `uv.lock` regenerated (if deps changed)
