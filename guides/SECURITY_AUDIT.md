# Tenant-isolation audit — 2026-08-21

Question asked: *can anyone read or send traces to a workspace they're not part of?* Scope: every
backend route, every Postgres/ClickHouse query, the auth flows, outbound HTTP, the SDK.

## Verdict

Data-layer isolation holds. Every router resolves `project_id` from the credential
(`api/auth.get_project_id` → `auth/principal.resolve_principal`), every ClickHouse query binds
`project_id = {p:String}`, every Postgres get-by-id compares `row.project_id`, and child lookups
(case→replays, cluster→members, gate→cases) happen only after a scoped parent check. OTLP ingest
takes `project_id` from the key alone — no span attribute can override it. Share links are
verified by their own issuer and never reach `resolve_principal`. The frontend's workspace cookie
is httpOnly and re-validated against org membership on every backend request.

The holes were one level up — in the account flows and in what the backend is willing to call.

## Fixed in this pass

| Sev | Finding | Fix |
|---|---|---|
| HIGH | **Invite → account takeover.** The raw invite token is returned to the inviter. If the invited email already had an account, accepting re-attached it and minted a session for it — the password was ignored. Invite a user from org B, accept it yourself, log in as them. | `accept_invitation` verifies the existing account's password before consuming the token (`test_invite_takeover.py`). |
| HIGH (hosted) | **SSRF via agent endpoint / monitor webhooks.** Any `http(s)://` URL was accepted and POSTed to from the worker, reply returned to the user. `http://clickhouse:8123/?query=SELECT … FROM events WHERE project_id='other'` is a cross-tenant read. | `infrastructure/net.assert_public_url` at save and send time; prod-on by default (`ALLOW_PRIVATE_URLS`) (`test_net_guard.py`). |
| MED | **Ingest keys were root keys** — wipe workspace, set OpenRouter spend key, delete conversations, re-point the agent endpoint. A leaked CI key = full compromise. | 16 destructive/secret routes now `require_user`; dev mode grants the key OWNER so the open dashboard keeps working (`test_ingest_key_scope.py`). |
| MED | **No rate limiting** on login / register / forgot / reset / accept. | Per-IP fixed window in Redis, fail-open (`api/ratelimit.py`, `test_ratelimit.py`). |
| — | Auth dependency pinned a Postgres connection for the whole request (the second half of the `too many clients` outage). | `get_principal` releases it after resolving. |

## Verified safe (no change)

JWT alg pinned (HS256 local / RS256 Clerk), issuer + required claims checked, JWT-shaped tokens
never fall through to the key lookup · argon2id with timing-equalised miss · invite/reset tokens
256-bit, stored hashed, single-use · Stripe webhook signature-verified, refuses to boot without the
secret · CORS localhost regex dropped in prod · OTLP body capped · assistant uploads capped and
project-prefixed in S3, ids regex-checked · ClickHouse SQL fully parameterised, sort keys
whitelisted · MCP + assistant tools re-enter the routers with the caller's own headers · SDK uses
`urllib` default TLS, no `verify=False`; the seeder passes the key via env to a list-args `Popen`.

## Still open, ranked

1. **Stateless sessions, no revocation.** Password change/reset and member removal do not evict
   an attacker's existing session (it lasts up to 7 days; membership *is* re-checked per request,
   so removal does revoke workspace access — but not the account). Fix: `token_version` on
   `users`, bumped on password change/reset, checked in `_resolve_local_jwt`. One migration.
2. **`tracely_dev_key` is live on any non-prod deployment in local mode.** A reachable staging
   box has a well-known root-ish key (now: read + ingest only, after this pass). Seed it only when
   `AUTH_MODE=dev`.
3. **`/health/queue` is unauthenticated** — queue depth and ingest freshness are visible to
   anyone. Information only.
4. **No ingest-key rotation endpoint.** Keys are created with the workspace and listed on
   `/auth/me`; revoking one means deleting the workspace.
5. **Rate limiter trusts the first `X-Forwarded-For` hop** — spoofable by a direct caller. It's a
   brake, not a boundary; pin to the proxy's hop count if credential stuffing shows up.
6. **SSRF guard has a check-then-connect gap** (DNS rebinding). Pinning the resolved IP into the
   `httpx` transport is the upgrade.
