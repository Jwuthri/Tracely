"""Worker entrypoint: `celery -A tracely_workers.worker worker`.
The Celery app + tasks live in tracely (shared with the API producer)."""

from __future__ import annotations

import tracely.tasks  # noqa: F401  (register tasks)
from tracely.celery_app import celery_app

app = celery_app
