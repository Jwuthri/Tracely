# Deploy Tracely to Railway

A pre-defined deployment for the whole Tracely stack. Four stateful dependencies come from Railway's
one-click templates; the three app services (backend API, Celery worker, Next.js frontend) deploy from
this repo using the config files in this directory.

```
                 ┌──────────────────── Railway project ────────────────────┐
  SDK / CI  ───▶ │  backend (public)  ──┐                                   │
  (OTLP)         │  frontend (public) ──┤  private network (*.railway.internal, IPv6/IPv4)
  browser   ───▶ │  worker (private)  ──┤                                   │
                 │     │  │  │  │       ▼                                    │
                 │   Postgres(pgvector) · ClickHouse · Redis · MinIO  (templates, private + volumes)
                 └─────────────────────────────────────────────────────────┘
```

| Service | Source | Public? | Notes |
|---|---|---|---|
| **Postgres** | pgvector template | no | registry DB; needs the `vector` extension (migration `0005` runs `CREATE EXTENSION`) |
| **ClickHouse** | ClickHouse template | no | events/scores; HTTP on 8123; template binds IPv6 |
| **Redis** | Redis template/plugin | no | Celery broker + result backend |
| **MinIO** | MinIO template | no | S3 blob store (raw OTLP = source of truth); bucket auto-created by backend pre-deploy |
| **backend** | this repo, `Dockerfile.backend` | **yes** | FastAPI; public domain = the OTLP ingest endpoint for SDK/CI |
| **worker** | this repo, `Dockerfile.backend` | no | Celery worker (scoring + failure intelligence) |
| **frontend** | this repo, `frontend/Dockerfile.railway` | **yes** | Next.js UI; proxies to the backend over the private network |

---

## 1. Create the project + the four dependency services

In a new Railway project, add each from the template gallery (**New → Database/Template**):

- **Postgres + pgvector** — https://railway.com/deploy/postgres-with-pgvector-engine  (rename the service to `Postgres`)
- **ClickHouse** — https://railway.com/deploy/clickhouse-server  (rename to `ClickHouse`)
- **Redis** — Railway built-in (**New → Database → Redis**)
- **MinIO** — https://railway.com/deploy/minio-object-storage  (rename to `MinIO`)

Each provisions a persistent **volume** automatically. Keep them all private (no public domain).

## 2. Create the three app services from this repo

For **each** of `backend`, `worker`, `frontend`: **New → GitHub Repo →** select this repo, then in the
service's **Settings**:

- **backend** — Config-as-code path: `deploy/railway/backend.json`
- **worker** — Config-as-code path: `deploy/railway/worker.json`
- **frontend** — Config-as-code path: `deploy/railway/frontend.json`

(The Dockerfile path, start command, healthcheck, and the backend's migration pre-deploy command all
come from those files — see [`config-as-code`](https://docs.railway.com/reference/config-as-code). The
config path is absolute from the repo root and does **not** follow any "Root Directory" setting, so
leave Root Directory empty — all three build from the repo root.)

Give **backend** and **frontend** a public domain (**Settings → Networking → Generate Domain**). Leave
**worker** private.

## 3. Set environment variables

Copy from [`.env.railway.example`](./.env.railway.example). The shared block (Postgres/ClickHouse/
Redis/MinIO/auth) goes on **both** `backend` and `worker` — easiest via **Project → Shared Variables**,
then reference `${{shared.NAME}}`. Then the per-service extras.

Must-set by hand:
- **`SESSION_SECRET`** on backend+worker (for `AUTH_MODE=local`) — `openssl rand -hex 32`.
- **`AUTH_MODE`** (backend+worker) and **`NEXT_PUBLIC_AUTH_MODE`** (frontend) — keep them equal
  (`local` for self-host, `clerk` for hosted SaaS, `dev` to run open with no login).
- For the frontend, also add `NEXT_PUBLIC_AUTH_MODE` (and any `NEXT_PUBLIC_CLERK_*`) as **Build**
  variables — they're inlined into the client bundle at `next build` time.

## 4. Deploy

Railway builds and deploys on push. On the **backend**, the `preDeployCommand` runs before traffic
cuts over:

```
ClickHouse DDL  →  alembic upgrade head  →  seed default project/key  →  ensure S3 bucket
```

All four steps are idempotent. On the very first deploy the `worker` may restart a few times until the
backend finishes creating the schema — that's expected and self-heals.

## 5. Post-deploy

- **Self-host (`local`)**: open `https://<frontend-public-domain>` → **Create your workspace** → you're
  the OWNER. Invite teammates from **Settings → Team**. Your ingest key is under **Settings → API keys**.
- **Point the SDK/CI at the backend's public domain** for trace ingest:
  ```python
  tracely.init(endpoint="https://<backend-public-domain>", api_key="<ingest-key>")
  ```
- **Hosted (`clerk`)**: set `CLERK_ISSUER` (backend) + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`/
  `CLERK_SECRET_KEY` (frontend, publishable also as a Build var). Configure Clerk sign-in/up URLs to
  `/sign-in` and `/sign-up`.

---

## Notes & gotchas

- **IPv6 binding.** Railway's private network is IPv6 (IPv4 too on environments created after Oct 2025).
  Our start commands bind `::` (`uvicorn --host ::`, `next start -H ::`) so both public edge and private
  service-to-service traffic reach them. The ClickHouse/MinIO templates already bind IPv6.
- **PORT.** Railway injects `$PORT`; the start commands honor it. We pin `PORT=8000` on backend so the
  frontend can reach it privately at a known port (`TRACELY_API=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:${{backend.PORT}}`).
- **Private vs public.** Service-to-service uses `http://<svc>.railway.internal` (already encrypted —
  no TLS, no egress cost). Only `backend` (SDK/CI ingest) and `frontend` (UI) need public domains; the
  browser never calls the backend directly (the Next server proxies everything).
- **`NEXT_PUBLIC_AUTH_MODE` is build-time-inlined.** Changing it requires a frontend rebuild (Railway
  rebuilds on each deploy, so a redeploy is enough).
- **Postgres driver URLs.** The app needs `postgresql+asyncpg://…` (runtime) and `postgresql+psycopg://…`
  (Alembic); we build both from the pgvector template's `PG*` parts since we can't re-prefix its
  `DATABASE_URL`.
- **Rotate the dev key.** Seeding creates the well-known `tracely_dev_key` for continuity. On a public
  deployment, mint a fresh ingest key and retire it (it's a project secret).
- **Scaling the worker** is `numReplicas` in the dashboard; it uses `--pool=solo`, so add replicas
  rather than threads.

## Optional: publish as a reusable template

Once the project is wired and green, **Project → Settings → Generate Template** turns it into a
one-click "Deploy on Railway" template (services + env wiring serialized). Share that URL to let others
deploy the whole stack in one click.
