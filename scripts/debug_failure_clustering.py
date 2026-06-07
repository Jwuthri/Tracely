"""Step through Tracely's failure-clustering pipeline for a specific trace.

Usage (from repo root, with `make infra-up` running):
    uv run python scripts/debug_failure_clustering.py --list
    uv run python scripts/debug_failure_clustering.py --trace-id <TRACE_ID>
    uv run python scripts/debug_failure_clustering.py --trace-id <TRACE_ID> --semantic
    uv run python scripts/debug_failure_clustering.py --trace-id <TRACE_ID> --break-before

How it reaches the Docker containers
------------------------------------
The repo's `.env` (next to docker-compose.yml) points every URL at `localhost:<port>`,
and docker-compose forwards those ports to the host:
    postgres:5432  ->  host:5432   (the `tracely` registry; pgvector lives here)
    clickhouse:8123 -> host:8123   (`events`, `scores` — the OLAP store)
    redis:6379     ->  host:6379   (Celery broker; unused by this script)
    minio:9000     ->  host:9000   (raw OTLP blobs; unused here)
Heads-up: the user's host also runs a native Postgres on 5432 that has no `tracely`
role — if connections fail with "role does not exist", the container isn't up or
something else is holding 5432. Run `docker compose ps postgres` to check.

Settings come from `tracely.config.Settings` (pydantic-settings, reads `.env`).
This script does no manual env wiring — it just imports the module and lets the
existing config machinery point us at the containers.

Where to set breakpoints
------------------------
This script calls into two real entry points:

  Structural (cheap, deterministic, no LLM):
      backend/tracely/eval_runner.py:51      evaluate_run()
      backend/tracely/cluster.py:57          cluster_failure()
      backend/tracely/cluster.py:43          _signature()   <- masked sig before sha256

  Semantic (HDBSCAN + LangGraph agent, needs OPENAI_API_KEY):
      backend/tracely/fi.py:179              rebuild_clusters()
      backend/tracely/fi.py:51               embedding_text()
      backend/tracely/agents.py              analyze_cluster / consolidate

Drop a `breakpoint()` in any of those, then run this script. Or pass
`--break-before` to drop into pdb here so you can `s`tep into the call.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sqlalchemy import text

from tracely import clickhouse
from tracely.config import settings
from tracely.db import SyncSessionLocal
from tracely.regression import _root, read_trace_spans


def resolve_project_id(explicit: str | None) -> str:
    """Use --project-id if given, otherwise the (single) seeded project."""
    if explicit:
        return explicit
    with SyncSessionLocal() as s:
        rows = s.execute(text("SELECT id, name FROM projects ORDER BY created_at LIMIT 5")).all()
    if not rows:
        sys.exit("no projects in Postgres — run `make seed` first")
    if len(rows) > 1:
        print(f"multiple projects found, using the oldest: {rows[0].name} ({rows[0].id})")
        for r in rows[1:]:
            print(f"  (skipped) {r.name} {r.id}")
    return rows[0].id


def list_failing_traces(project_id: str, limit: int = 20) -> None:
    """Print recent traces that have at least one FAIL score — copy-paste fodder."""
    ch = clickhouse.get_client()
    rows = ch.query(
        """
        SELECT trace_id, max(created_at) AS last_seen, count() AS fail_count
        FROM scores FINAL
        WHERE project_id = {p:String} AND source = 'EVAL' AND verdict = 'FAIL'
        GROUP BY trace_id ORDER BY last_seen DESC LIMIT {n:UInt32}
        """,
        parameters={"p": project_id, "n": limit},
    ).result_rows
    if not rows:
        print("no failing traces found — try `make demo-failures` first")
        return
    print(f"{'trace_id':<40}  {'last_seen':<26}  fails")
    print("-" * 80)
    for tid, ts, n in rows:
        print(f"{tid:<40}  {str(ts):<26}  {n}")


def summarize_spans(spans: list[dict]) -> None:
    """One-line per span so you can eyeball the trace shape before stepping in."""
    root = _root(spans)
    print(f"\ntrace root: agent_id={root.get('agent_id')!r}  agent_run_id={root.get('agent_run_id')!r}")
    print(f"  {len(spans)} spans, {sum(1 for s in spans if s.get('level') == 'ERROR')} errors")
    for s in spans[:15]:
        flag = " ERR" if s.get("level") == "ERROR" else "    "
        msg = (s.get("status_message") or "")[:60]
        print(f"  {flag}  {s.get('type', '?'):<10}  {(s.get('name') or '?')[:35]:<35}  {msg}")
    if len(spans) > 15:
        print(f"  ... ({len(spans) - 15} more)")


def run_structural(project_id: str, trace_id: str, break_before: bool) -> None:
    """Real path: re-run the project's evaluators, then cluster_failure() on any FAILs."""
    from tracely.eval_runner import evaluate_run

    ch = clickhouse.get_client()
    spans = read_trace_spans(ch, project_id, trace_id)
    if not spans:
        sys.exit(f"trace {trace_id!r} has no spans in ClickHouse — wrong project? not ingested yet?")
    summarize_spans(spans)

    print("\n>>> calling evaluate_run() — this re-runs evaluators and calls cluster_failure()")
    print("    set breakpoint() in backend/tracely/cluster.py:_signature or :cluster_failure")
    if break_before:
        print("    --break-before: dropping into pdb; `s` to step into evaluate_run")
        breakpoint()
    result = evaluate_run(project_id, trace_id)
    print(f"<<< evaluate_run returned: {result}")
    show_clusters_for_trace(project_id, trace_id)


def run_semantic(project_id: str, break_before: bool) -> None:
    """Project-wide: embed every failing trace, HDBSCAN, then LLM-name each cluster."""
    if not settings.openai_api_key:
        sys.exit("OPENAI_API_KEY not set in .env — semantic path needs it")
    from tracely import fi

    print("\n>>> calling fi.rebuild_clusters() — embeds all failing traces, HDBSCAN, LangGraph agent")
    print("    set breakpoint() in backend/tracely/fi.py:rebuild_clusters or :embedding_text")
    if break_before:
        print("    --break-before: dropping into pdb; `s` to step into rebuild_clusters")
        breakpoint()
    result = fi.rebuild_clusters(project_id)
    print(f"<<< rebuild_clusters returned: {result}")


def show_clusters_for_trace(project_id: str, trace_id: str) -> None:
    """After clustering, show which FailureCluster row(s) this trace landed in."""
    with SyncSessionLocal() as s:
        rows = s.execute(
            text(
                """
                SELECT c.id, c.label, c.taxonomy, c.count, c.status
                FROM failure_clusters c
                JOIN cluster_members m ON m.cluster_id = c.id
                WHERE c.project_id = :p AND m.trace_id = :t
                """
            ),
            {"p": project_id, "t": trace_id},
        ).all()
    if not rows:
        print("(trace did not land in any cluster — likely no FAIL scores were emitted)")
        return
    print("\nclusters this trace belongs to:")
    for r in rows:
        print(f"  {r.id}  status={r.status}  count={r.count}  [{r.taxonomy}] {r.label}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trace-id", help="trace_id to cluster")
    p.add_argument("--project-id", help="override the default (first) project")
    p.add_argument("--semantic", action="store_true", help="also run the LLM/HDBSCAN rebuild")
    p.add_argument("--break-before", action="store_true", help="drop into pdb just before each call")
    p.add_argument("--list", action="store_true", help="list recent failing traces and exit")
    args = p.parse_args()

    project_id = resolve_project_id(args.project_id)
    print(f"project_id = {project_id}")
    print(f"pg = {settings.database_url}")
    print(f"ch = {settings.clickhouse_host}:{settings.clickhouse_port}/{settings.clickhouse_database}")

    if args.list:
        list_failing_traces(project_id)
        return
    if not args.trace_id:
        sys.exit("--trace-id required (or pass --list to see options)")

    run_structural(project_id, args.trace_id, args.break_before)
    if args.semantic:
        run_semantic(project_id, args.break_before)


if __name__ == "__main__":
    main()
