# Deploying Tracely to production

The local docker stack is the dev environment — it boots with `AUTH_MODE=dev` and seeds a published
`tracely_dev_key`. **Neither of those is safe in prod.** This document is the runbook for a real
deploy: required env vars, the guards that fail-fast if you miss one, the worker pool, backups,
and the post-deploy verification.

We target Railway (Postgres + ClickHouse + Redis + MinIO managed there), but the same checklist
works on any host running the same two containers.

---

## 1. The prod refuse-to-boot guards

The backend fails fast at startup in these cases. **Don't bypass — fix them.**

| Guard | Where | Why |
| --- | --- | --- |
| `TRACELY_ENV=prod` + `AUTH_MODE=dev` → `ValueError` at config load | `tracely/config.py:_validate_auth` | Dev mode has no human auth; the ingest key is the only credential. Booting prod in dev mode is world-pwnable. |
| `TRACELY_ENV=prod` + `tracely_dev_key` still in `ingest_keys` → `RuntimeError` in `lifespan` | `api/main.py:_refuse_dev_key_in_prod` | The dev key is published in the docs. If the prod DB still has it (e.g. migrated from a dev snapshot), shut down before serving the first request. |
| `AUTH_MODE=local` + `SESSION_SECRET` shorter than 32 chars → `ValueError` | `tracely/config.py:_validate_auth` | Weak HS256 keys are forgeable. |
| `AUTH_MODE=clerk` + no `CLERK_ISSUER` → `ValueError` | same | Clerk verification needs the issuer to fetch JWKS. |

If `tracely_dev_key` is in your prod DB (a fresh prod deploy never seeds it — see
`seeding_service.py`), delete it before you boot:

```sql
DELETE FROM ingest_keys WHERE key = 'tracely_dev_key';
```

---

## 2. Required env vars

```dotenv
# Identity
TRACELY_ENV=prod                     # flips on the guards + tightens CORS + skips dev-key seeding

# Auth — pick ONE
AUTH_MODE=local                      # email/password owned by this backend
SESSION_SECRET=...                   # `openssl rand -hex 32` (>=32 chars required)
# …or
AUTH_MODE=clerk
CLERK_ISSUER=https://<slug>.clerk.accounts.dev
CLERK_AUDIENCE=...                   # optional; pins the JWT 'aud'

# Postgres + ClickHouse + Redis (Railway-injected URLs are fine)
DATABASE_URL=postgresql+asyncpg://...
ALEMBIC_DATABASE_URL=postgresql+psycopg://...
CLICKHOUSE_HOST=...
CLICKHOUSE_USER=...
CLICKHOUSE_PASSWORD=...
REDIS_URL=redis://...

# Object storage (event blobs)
S3_ENDPOINT_URL=...
S3_BUCKET=tracely-events
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...

# LLM (judge, failure-intel agents, rolling summary, meta-analysis)
OPENROUTER_API_KEY=...
OPENAI_API_KEY=...                   # embeddings only

# Hosted frontend origin (CORS allow-list — wildcard localhost is OFF in prod)
FRONTEND_ORIGIN=https://app.your-domain.com
APP_BASE_URL=https://app.your-domain.com

# Worker pool (real concurrency — see §3)
CELERY_POOL=prefork
CELERY_CONCURRENCY=4

# Optional: Sentry (no-op when DSN is unset; install sentry-sdk in the prod image to activate)
SENTRY_DSN=...
SENTRY_ENVIRONMENT=prod
```

---

## 3. Celery worker pool

Local dev uses `--pool=solo --concurrency=1` because the failure-intelligence stack
(numba / UMAP / HDBSCAN) was historically fork-fragile. Prod sets:

```dotenv
CELERY_POOL=prefork
CELERY_CONCURRENCY=4   # tune to vCPU; the docker-compose worker reads both vars
```

If a numba/UMAP fork bug resurfaces under prefork, switch to `CELERY_POOL=threads` (same env var,
the rebuild-clusters task is mostly NumPy + I/O so threads are fine).

Run **at least two worker replicas** so a single hang doesn't drop ingestion. `task_acks_late=True`
+ `visibility_timeout=3h` mean an unacked task is redelivered after 3 hours — enough headroom for
the slowest cluster-rebuild without double-running fast ingest tasks.

---

## 4. Backups (the only P0 we can't automate)

There is no automatic backup of Tracely's own data. Enable them in your provider's UI.

### Railway

- **Postgres** → service → *Backups* → toggle daily snapshots; pick a retention window (7-30 days).
- **ClickHouse** → service → *Backups* → same. ClickHouse snapshots include `events` and `scores`;
  point-in-time recovery isn't available, so daily is the granularity.
- Redis is **not** backup-critical (it holds the Celery queue; a queue replay = retry, not data loss).
- MinIO/S3 → enable versioning on the `tracely-events` bucket; OTLP blobs are immutable, so the
  cost is just one extra version per write.

### Restore test (do this at least once)

1. Take a fresh snapshot, then restore it into a `tracely-restore` service.
2. Point a throwaway backend at the restored URLs (`DATABASE_URL`, `CLICKHOUSE_HOST`).
3. Boot — the refuse-to-boot guard catches a forgotten dev key here. Open `/traces`.
4. Tear down. You now know your RTO.

---

## 5. Health probe

`GET /health` returns **200** only when ClickHouse and Postgres both answer; otherwise **503** with
a per-dep status payload. Wire your platform's liveness/readiness probes to it:

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
  interval: 10s
  timeout: 3s
  retries: 6
  start_period: 30s
```

A 503 means one of your dependencies is down; check the JSON body for which.

---

## 6. CORS

In prod `FRONTEND_ORIGIN` is the only allow-listed origin. Localhost is **not** allowed (controlled
by `settings.is_prod` in `api/main.py`). If you serve the frontend from multiple hosts (canary,
staging) set `FRONTEND_ORIGIN` to the user-facing one and use a same-origin proxy for the rest.

---

## 7. Post-deploy verification

After the deploy, run this from a workstation:

```bash
HOST=https://api.your-domain.com

# 1. /health should be 200 with both deps OK
curl -s "$HOST/health" | jq

# 2. The dev key MUST be invalid in prod
curl -s -w "\nHTTP %{http_code}\n" -H "Authorization: Bearer tracely_dev_key" "$HOST/api/sessions?limit=1"
# expect:  HTTP 401   (any 2xx response = you forgot the guard)

# 3. CORS must NOT allow localhost
curl -s -o /dev/null -w "%{http_code}\n" -H "Origin: http://localhost:3001" -H "Access-Control-Request-Method: GET" -X OPTIONS "$HOST/api/sessions"
# expect:  the response lacks Access-Control-Allow-Origin for localhost (compare against FRONTEND_ORIGIN)
```

If any of those three fail, **roll back** — don't try to patch a serving instance.
