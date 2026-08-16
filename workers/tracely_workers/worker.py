"""Worker entrypoint: `celery -A tracely_workers.worker worker`.
The Celery app + tasks live in tracely (shared with the API producer)."""

from __future__ import annotations

import structlog
from celery.signals import celeryd_init

import tracely.workers.tasks  # noqa: F401  (importing registers tasks on celery_app)
from tracely.config import settings
from tracely.infrastructure.queue.celery_app import celery_app

app = celery_app
log = structlog.get_logger()


@celeryd_init.connect
def _init_sentry(**_: object) -> None:
    """Same optional Sentry hook the API has (`api/main.py`), for the process where the work
    actually happens: evaluation, clustering, gate runs. A task that dies here dies silently —
    the API stays green and the UI just stops filling in."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
    except ImportError:
        log.warning("sentry_skipped_no_sdk", hint="pip install sentry-sdk")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.tracely_env,
        integrations=[CeleryIntegration()],
        traces_sample_rate=0.0,
    )
