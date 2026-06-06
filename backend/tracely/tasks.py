"""Celery ingestion task: read the durable OTLP blob, map to events, resolve registry
ids, insert into ClickHouse. This is the async half of the write path (worker side).
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from tracely import blobstore, clickhouse, registry
from tracely.celery_app import celery_app
from tracely.config import settings
from tracely.db import SyncSessionLocal
from tracely.events import EVENT_COLUMNS, to_rows
from tracely.otel import parse_otlp_traces, parse_otlp_traces_json

log = structlog.get_logger()


def _apply_default_agent(events: list[dict]) -> None:
    """Attribute agent-less spans to a fallback agent so agent-scoped features (failure clusters,
    CI gates) still apply to plain LLM calls. Within a trace, an empty-agent span inherits the
    trace's agent (its app-root's, else any sibling's); only a trace with no agent anywhere gets
    the configured default. `tracely.agent.id` is mirrored into metadata so the UI shows the slug."""
    default_slug = settings.default_agent_slug
    if not default_slug:
        return
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_trace[ev.get("trace_id")].append(ev)
    for evs in by_trace.values():
        root = next((e for e in evs if e.get("is_app_root")), None)
        trace_agent = (
            (root.get("agent_slug") if root else "")
            or next((e.get("agent_slug") for e in evs if e.get("agent_slug")), "")
            or default_slug
        )
        for e in evs:
            if not e.get("agent_slug"):
                e["agent_slug"] = trace_agent
                e.setdefault("metadata", {})["tracely.agent.id"] = trace_agent


@celery_app.task(name="tracely.ingest_otlp_blob", bind=True, max_retries=6, default_retry_delay=5)
def ingest_otlp_blob(self, project_id: str, key: str, content_type: str) -> dict:
    try:
        raw = blobstore.get_blob(key)
        is_json = "json" in (content_type or "")
        events = (parse_otlp_traces_json if is_json else parse_otlp_traces)(raw, project_id)
        if not events:
            return {"events": 0}

        _apply_default_agent(events)  # agent-less traces -> fallback agent (inherits within a trace)

        # Resolve agent slug -> registry UUID (and version ref -> UUID), then strip helper keys.
        with SyncSessionLocal() as session:
            slug_to_id: dict[str, str] = {}
            for ev in events:
                slug = ev.pop("agent_slug", "")
                ver = ev.pop("agent_version_ref", "")
                if slug:
                    if slug not in slug_to_id:
                        slug_to_id[slug] = registry.upsert_agent(session, project_id, slug)
                    ev["agent_id"] = slug_to_id[slug]
                    if ver:
                        ev["agent_version_id"] = registry.upsert_agent_version(
                            session, slug_to_id[slug], ver
                        )

        client = clickhouse.get_client()
        clickhouse.insert_rows(client, "events", EVENT_COLUMNS, to_rows(events))
        log.info("ingested", project_id=project_id, key=key, events=len(events))

        # Online evaluation: fire (debounced) once per trace so late spans settle first.
        for trace_id in {ev.get("trace_id") for ev in events if ev.get("trace_id")}:
            evaluate_run_task.apply_async((project_id, trace_id), countdown=4)

        return {"events": len(events)}
    except Exception as exc:  # transient failures -> retry with backoff
        log.warning("ingest_failed", key=key, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="tracely.evaluate_run", bind=True, max_retries=3, default_retry_delay=3)
def evaluate_run_task(self, project_id: str, trace_id: str) -> dict:
    from tracely import eval_runner

    try:
        return eval_runner.evaluate_run(project_id, trace_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="tracely.rebuild_clusters", bind=True, max_retries=0)
def rebuild_clusters_task(self, project_id: str) -> dict:
    from tracely import fi

    return fi.rebuild_clusters(project_id)
