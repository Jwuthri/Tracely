# `workers/` — the Celery worker runtime

The deployable worker process. It is a **thin shim** (`tracely_workers/worker.py`, ~9 lines) that imports the backend's `tracely` package and runs its Celery tasks — the **async half of the write path** plus online evaluation and failure clustering. All the actual logic lives in [`backend/`](../backend/); this package exists only so the worker can be built, deployed, and scaled as its own process.

```python
# tracely_workers/worker.py
import tracely.workers.tasks                                # registers the tasks
from tracely.infrastructure.queue.celery_app import celery_app
app = celery_app
```

## What it runs

The same `celery_app` the API enqueues onto (Redis broker). Tasks (`backend/tracely/workers/tasks.py`):

| Task | Triggered by | Does |
|---|---|---|
| `ingest_otlp_blob` | `POST /v1/traces` (per batch) | read the durable S3 blob → map OTLP → resolve agent slugs → insert into ClickHouse `events` → enqueue `evaluate_run_task` (4s debounce). |
| `evaluate_run_task` | after ingest, per trace | run the project's evaluators → write `scores` → cheap structural failure clustering. |
| `rebuild_clusters_task` | "Analyze failures" in the UI / `POST /api/clusters/rebuild` | semantic failure intelligence (embed → cluster → LLM issue write). |

## Run it

```bash
make workers
# = uv run celery -A tracely_workers.worker worker --pool=solo --loglevel=info
```
In Docker it's the `worker` service (same `tracely-backend` image, source volume-mounted).

> ⚠️ **The worker does not hot-reload.** After editing any worker / eval / failure-intelligence / OTLP-mapping code, restart it: `docker compose restart worker` (or restart `make workers`). A stale worker silently runs the old code — this has bitten us.

## Key decisions (and why)

1. **Separate package, shared domain.** The worker imports `tracely` rather than redefining anything, so the API producer and the worker consumer can never drift on mapping/DB logic — yet the worker deploys and scales independently of the API.
2. **`--pool=solo` in dev.** Simplest, and avoids fork issues with the native numba/UMAP/HDBSCAN stack used by failure intelligence. Production can switch pools/concurrency.
3. **It's a queue consumer, not a server.** No HTTP surface; everything reaches it via Redis, so backpressure and retries are the queue's job (tasks set `max_retries` + backoff).
