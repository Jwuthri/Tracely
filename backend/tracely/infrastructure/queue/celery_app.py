"""Shared Celery app. The API (producer) and worker (consumer) both import this.
Tasks live in tracely.workers.tasks (included via `include`).
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

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
    # With acks_late on Redis, an unacked task is redelivered after `visibility_timeout` — so a long
    # task (cluster rebuild, batch eval) that outruns the default 1h gets run a SECOND time while the
    # first is still going (double work, double LLM spend). Raise the window past our slowest task.
    broker_transport_options={"visibility_timeout": 3 * 60 * 60},  # 3h
    # Bound task runtime so a hung task can't pin the (solo) worker forever.
    task_time_limit=30 * 60,  # hard kill at 30m
    task_soft_time_limit=25 * 60,  # SoftTimeLimitExceeded at 25m (lets a task clean up)
    # Periodic schedule: drive the monitoring engine every 5 minutes. (Celery beat must be running
    # to actually fire — `celery -A tracely beat`. In local docker we run it alongside the worker
    # via `celery worker -B`.) Quiet by default; only fires when a monitor condition crosses its
    # threshold + the dedup interval has elapsed.
    beat_schedule={
        "tracely.evaluate_monitors-every-5-min": {
            "task": "tracely.evaluate_monitors",
            "schedule": crontab(minute="*/5"),
        },
    },
    timezone="UTC",
)
