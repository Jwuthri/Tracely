"""Shared Celery app. The API (producer) and worker (consumer) both import this.
Tasks live in tracely.workers.tasks (included via `include`).
"""

from __future__ import annotations

from celery import Celery

from tracely.config import settings

celery_app = Celery(
    "tracely",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tracely.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue="ingestion",
    task_acks_late=True,
    worker_prefetch_multiplier=4,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
