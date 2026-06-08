"""Ingestion service: the OTLP → blob → enqueue producer side AND the worker-side
"read blob, map, persist" pipeline.

The class wraps the worker-side stages (`process_blob`) so each step is named and testable;
`ingest_otlp` stays as a module-level function for the FastAPI router (it has nothing to do
with a long-lived service object — it's one fire-and-forget action).
"""

from __future__ import annotations

import uuid
from collections import defaultdict

import structlog

from tracely.config import settings
from tracely.infrastructure.blob import s3 as blobstore
from tracely.infrastructure.clickhouse.client import get_client, insert_rows
from tracely.infrastructure.clickhouse.events_schema import EVENT_COLUMNS, to_rows
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.registry import agents as registry
from tracely.otel import parse_otlp_traces, parse_otlp_traces_json

log = structlog.get_logger()


def ingest_otlp(project_id: str, content_type: str, raw: bytes) -> str:
    """Blob-first ingestion entry: upload the raw OTLP body to S3, then enqueue the worker.

    Mirrors Langfuse `processEventBatch`: nothing is queued unless the blob is durable.
    """
    # Local import: avoids a circular path through `workers.tasks -> celery_app -> include`.
    from tracely.workers.tasks import ingest_otlp_blob

    batch_id = uuid.uuid4().hex
    key = blobstore.event_blob_key(project_id, batch_id, content_type)
    blobstore.put_blob(key, raw, content_type or "application/x-protobuf")
    ingest_otlp_blob.delay(project_id, key, content_type or "")
    return batch_id


class IngestionService:
    """Worker-side pipeline: blob → events → registry resolve → ClickHouse insert → schedule
    online eval. Called from the `ingest_otlp_blob` Celery task."""

    def process_blob(self, project_id: str, key: str, content_type: str) -> dict:
        raw = blobstore.get_blob(key)
        is_json = "json" in (content_type or "")
        events = (parse_otlp_traces_json if is_json else parse_otlp_traces)(raw, project_id)
        if not events:
            return {"events": 0, "trace_ids": []}

        # agent-less traces -> fallback agent (inherits within a trace)
        self._attribute_default_agent(events)
        self._resolve_registry_ids(project_id, events)

        client = get_client()
        insert_rows(client, "events", EVENT_COLUMNS, to_rows(events))

        trace_ids = sorted({ev.get("trace_id") for ev in events if ev.get("trace_id")})
        log.info("ingested", project_id=project_id, key=key, events=len(events))
        return {"events": len(events), "trace_ids": list(trace_ids)}

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _attribute_default_agent(events: list[dict]) -> None:
        """Attribute agent-less spans to a fallback agent so agent-scoped features (failure
        clusters, CI gates) still apply to plain LLM calls. Within a trace, an empty-agent span
        inherits the trace's agent (its app-root's, else any sibling's); only a trace with no
        agent anywhere gets the configured default. `tracely.agent.id` is mirrored into
        metadata so the UI shows the slug."""
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

    @staticmethod
    def _resolve_registry_ids(project_id: str, events: list[dict]) -> None:
        """Resolve `agent_slug` → registry UUID (and `agent_version_ref` → UUID), then strip
        helper keys so they don't get written to ClickHouse."""
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
