"""Celery tasks: thin dispatch into the service classes.

`tracely_workers.worker` imports this module to register the tasks on the shared Celery app.
"""

from __future__ import annotations

import structlog

from tracely.infrastructure.queue.celery_app import celery_app
from tracely.services.evaluation_service import EvaluationService
from tracely.services.failure_intel_service import FailureIntelService
from tracely.services.ingestion_service import IngestionService

log = structlog.get_logger()


@celery_app.task(name="tracely.ingest_otlp_blob", bind=True, max_retries=6, default_retry_delay=5)
def ingest_otlp_blob(self, project_id: str, key: str, content_type: str) -> dict:
    try:
        result = IngestionService().process_blob(project_id, key, content_type)
        # Online evaluation: fire (debounced) once per trace so late spans settle first.
        for trace_id in result.get("trace_ids", []):
            evaluate_run_task.apply_async((project_id, trace_id), countdown=4)
        return {"events": result.get("events", 0)}
    except Exception as exc:  # transient failures -> retry with backoff
        log.warning("ingest_failed", key=key, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="tracely.evaluate_run", bind=True, max_retries=3, default_retry_delay=3)
def evaluate_run_task(self, project_id: str, trace_id: str) -> dict:
    try:
        return EvaluationService().evaluate_trace(project_id, trace_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="tracely.rebuild_clusters", bind=True, max_retries=0)
def rebuild_clusters_task(self, project_id: str) -> dict:
    return FailureIntelService().rebuild_clusters(project_id)
