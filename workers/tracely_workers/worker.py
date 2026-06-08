"""Worker entrypoint: `celery -A tracely_workers.worker worker`.
The Celery app + tasks live in tracely (shared with the API producer)."""

from __future__ import annotations

import tracely.workers.tasks  # noqa: F401  (importing registers tasks on celery_app)
from tracely.infrastructure.queue.celery_app import celery_app

app = celery_app
