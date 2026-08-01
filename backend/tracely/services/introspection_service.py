"""Turn a Recording into a trace.

One entry point — `record(...)` — wraps a piece of Tracely's own work (grading a trace, driving a
scenario) and, on the way out, ships what happened down the ordinary ingest path so it lands in
ClickHouse like any other trace.

Three rules this module exists to hold:

1. **It can never break the work it observes.** Every failure here is logged and swallowed. A
   judge that graded correctly must not report an error because its recording failed to save.
2. **No nesting.** A recording already in progress wins; an inner `record()` is a no-op that keeps
   filing steps into the outer one. Without this, grading inside a scenario run would fork the
   trace in two and lose the connection between them.
3. **Ingest is inline, not queued.** Same reason emulated turns are (see `simulation_service`):
   the caller often holds the worker's only slot under `--pool=solo --concurrency=1`, so an
   enqueued blob would sit behind work that is waiting on us.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator

import structlog

from tracely.config import settings
from tracely.domain import introspection
from tracely.domain.introspection import Recording
from tracely.infrastructure.blob import s3 as blobstore
from tracely.services.ingestion_service import IngestionService

log = structlog.get_logger(__name__)


@contextlib.contextmanager
def record(
    kind: str,
    subject_id: str,
    name: str,
    *,
    project_id: str,
    agent_slug: str = "",
    env: str = "prod",
    subject_label: str = "",
) -> Iterator[Recording | None]:
    """Record everything Tracely does inside this block as a trace about `subject_id`.

    Yields the `Recording` so callers can set `.label` (the group new steps file under) and add
    non-LLM steps; yields None when recording is off or already in progress, so callers must
    tolerate None — `rec and rec.add(...)`.
    """
    if not settings.introspection_enabled or introspection.active() is not None:
        yield None
        return

    rec = Recording(
        kind=kind, subject_id=subject_id, name=name,
        project_id=project_id, agent_slug=agent_slug, env=env,
        subject_label=subject_label,
    )
    token = introspection._active.set(rec)
    try:
        yield rec
    finally:
        introspection._active.reset(token)
        _emit(rec)


def _emit(rec: Recording) -> None:
    """Ship the recording as OTLP. Best-effort by design — see rule 1 in the module docstring."""
    try:
        payload = introspection.payload(rec)
        if payload is None:
            return  # nothing happened worth a trace (no LLM call, no step)
        import json

        raw = json.dumps(payload).encode()
        key = blobstore.event_blob_key(rec.project_id, uuid.uuid4().hex, "application/json")
        blobstore.put_blob(key, raw, "application/json")
        IngestionService().process_blob(rec.project_id, key, "application/json")
    except Exception as exc:
        log.warning(
            "introspection_emit_failed",
            kind=rec.kind, subject_id=rec.subject_id, steps=len(rec.steps), error=str(exc),
        )
