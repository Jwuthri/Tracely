"""Celery tasks: thin dispatch into the service classes.

`tracely_workers.worker` imports this module to register the tasks on the shared Celery app.
"""

from __future__ import annotations

import structlog

from tracely.config import settings
from tracely.infrastructure.queue import eval_debounce
from tracely.infrastructure.queue.celery_app import celery_app
from tracely.services.evaluation_service import EvaluationService
from tracely.services.failure_intel_service import FailureIntelService
from tracely.services.ingestion_service import IngestionService

log = structlog.get_logger()


@celery_app.task(name="tracely.ingest_otlp_blob", bind=True, max_retries=6, default_retry_delay=5)
def ingest_otlp_blob(self, project_id: str, key: str, content_type: str) -> dict:
    try:
        result = IngestionService().process_blob(project_id, key, content_type)
        # Online evaluation: debounce per trace so a run whose spans span several OTLP batches is
        # evaluated ONCE after it goes quiet — not once per batch (wasted judge spend) and not on a
        # partial trace. Each batch bumps the trace's generation; the scheduled eval runs only if its
        # generation is still the latest when it fires (see infrastructure/queue/eval_debounce.py).
        for trace_id in result.get("trace_ids", []):
            gen = eval_debounce.bump(project_id, trace_id)
            evaluate_run_task.apply_async(
                (project_id, trace_id, gen), countdown=settings.eval_debounce_seconds
            )
        return {"events": result.get("events", 0)}
    except Exception as exc:  # transient failures -> retry with backoff
        log.warning("ingest_failed", key=key, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="tracely.evaluate_run", bind=True, max_retries=3, default_retry_delay=3)
def evaluate_run_task(self, project_id: str, trace_id: str, gen: int = 0) -> dict:
    # Debounce: skip if a newer batch for this trace arrived after we were scheduled — the later
    # task will evaluate the settled trace. `gen=0` is the ungated sentinel (always runs).
    if not eval_debounce.is_latest(project_id, trace_id, gen):
        return {"skipped": "superseded", "trace_id": trace_id}
    try:
        result = EvaluationService().evaluate_trace(project_id, trace_id)
    except Exception as exc:
        raise self.retry(exc=exc)
    # Real-time rolling summary: fold this turn into the thread's accumulating summary. Incremental
    # (only new spans are summarized) and best-effort — a summary failure must never fail the run.
    try:
        from tracely.services.rolling_summary_service import RollingSummaryService

        thread_id = result.get("thread_id") or trace_id
        RollingSummaryService().build_for_thread(project_id, thread_id, source="ingest")
    except Exception as exc:
        log.warning("rolling_summary_ingest_failed", trace_id=trace_id, error=str(exc))
    return result


@celery_app.task(name="tracely.rebuild_clusters", bind=True, max_retries=0)
def rebuild_clusters_task(self, project_id: str) -> dict:
    return FailureIntelService().rebuild_clusters(project_id)


@celery_app.task(name="tracely.evaluate_monitors", bind=True, max_retries=0)
def evaluate_monitors_task(self) -> dict:
    """Fire the monitoring engine for every enabled monitor in every project — driven by Celery
    beat (`beat_schedule` in `celery_app.py`). Best-effort: one bad monitor is logged + skipped,
    transient errors are NOT retried (the next beat tick will pick up where we left off)."""
    import asyncio

    from tracely.services.monitoring_service import MonitoringService

    try:
        return asyncio.run(MonitoringService().evaluate_all())
    except Exception as exc:  # CH outage / Redis blip — the next tick will retry
        log.warning("evaluate_monitors_failed", error=str(exc))
        return {"monitors": 0, "fired": 0, "error": str(exc)}
