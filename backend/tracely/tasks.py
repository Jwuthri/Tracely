"""Celery ingestion task: read the durable OTLP blob, map to events, resolve registry
ids, insert into ClickHouse. This is the async half of the write path (worker side).
"""

from __future__ import annotations

import structlog

from tracely import blobstore, clickhouse, registry
from tracely.celery_app import celery_app
from tracely.db import SyncSessionLocal
from tracely.events import EVENT_COLUMNS, to_rows
from tracely.otel import parse_otlp_traces, parse_otlp_traces_json

log = structlog.get_logger()


@celery_app.task(name="tracely.ingest_otlp_blob", bind=True, max_retries=6, default_retry_delay=5)
def ingest_otlp_blob(self, project_id: str, key: str, content_type: str) -> dict:
    try:
        raw = blobstore.get_blob(key)
        is_json = "json" in (content_type or "")
        events = (parse_otlp_traces_json if is_json else parse_otlp_traces)(raw, project_id)
        if not events:
            return {"events": 0}

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
        return {"events": len(events)}
    except Exception as exc:  # transient failures -> retry with backoff
        log.warning("ingest_failed", key=key, error=str(exc))
        raise self.retry(exc=exc)
