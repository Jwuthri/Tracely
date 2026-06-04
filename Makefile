.PHONY: help infra-up infra-down infra-prune install migrate migrate-ch migrate-pg seed backend workers frontend test send-trace demo-failures gate replay sdk-example fmt

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

infra-up:    ## start clickhouse, postgres, redis, minio
	docker compose up -d --wait

infra-down:  ## stop infra (keeps volumes)
	docker compose down

infra-prune: ## stop infra and delete volumes
	docker compose down -v

install:     ## sync python deps (uv, all workspace packages) + frontend deps (pnpm)
	uv sync --all-packages
	cd frontend && pnpm install

migrate: migrate-ch migrate-pg ## run all migrations

migrate-ch:  ## apply ClickHouse migrations
	uv run python -m tracely.ch_migrate

migrate-pg:  ## apply Postgres (Alembic) migrations
	cd backend && uv run alembic upgrade head

seed:        ## create the default project + ingest key (tracely_dev_key)
	uv run python -m tracely.seed

backend:     ## run FastAPI (ingestion + reads) on :8000
	uv run uvicorn tracely.api.main:app --reload --port 8000

workers:     ## run the Celery worker
	uv run celery -A tracely_workers.worker worker --pool=solo --loglevel=info

frontend:    ## run Next.js on :3000
	cd frontend && pnpm dev

test:        ## run backend tests
	uv run pytest -q backend/tests

send-trace:  ## post a sample OTLP trace to the running API
	uv run python scripts/send_test_trace.py

# Override the target when the API is not on :8000 — e.g. `make demo-failures TRACELY_API=http://localhost:8088`
TRACELY_API ?= http://localhost:8000
demo-failures: ## seed a mix of failing runs (errors + silent + hallucinations) for the clustering demo
	@for i in 1 2 3 4 5; do TRACELY_API=$(TRACELY_API) RANDOM=1 uv run python scripts/send_test_trace.py; done
	@for i in 1 2 3 4 5 6 7 8 9; do TRACELY_API=$(TRACELY_API) RANDOM=1 SILENT=1 uv run python scripts/send_test_trace.py; done
	@for i in 1 2 3 4 5; do TRACELY_API=$(TRACELY_API) RANDOM=1 HALLUCINATE=1 uv run python scripts/send_test_trace.py; done
	@echo "seeded — now hit 'Analyze failures' in the UI (or POST /api/clusters/rebuild)"

gate:        ## run the CI/CD regression gate locally for an agent (TRACELY_AGENT=planner)
	TRACELY_API=$(TRACELY_API) uv run tracely gate $${TRACELY_AGENT:-planner} --env $${GATE_ENV:-ci}

replay:      ## re-run the example agent on the promoted suite, then gate (ENTRYPOINT=weather_agent:run)
	TRACELY_API=$(TRACELY_API) PYTHONPATH=sdk/examples uv run tracely replay $${TRACELY_AGENT:-planner} \
		--entrypoint $${ENTRYPOINT:-weather_agent:run} --env $${GATE_ENV:-replay}

sdk-example: ## emit the demo trace via the Tracely SDK
	uv run python sdk/example.py

fmt:         ## format python
	uv run ruff format .
