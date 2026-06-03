"""Blob-first ingestion entrypoint (API side).

Mirrors Langfuse processEventBatch: upload the raw body to S3 (source of truth) BEFORE
enqueuing — nothing is queued unless the blob is durable — then enqueue the worker task.
"""

from __future__ import annotations

import uuid

from tracely import blobstore
from tracely.tasks import ingest_otlp_blob


def ingest_otlp(project_id: str, content_type: str, raw: bytes) -> str:
    batch_id = uuid.uuid4().hex
    key = blobstore.event_blob_key(project_id, batch_id, content_type)
    blobstore.put_blob(key, raw, content_type or "application/x-protobuf")  # durable first
    ingest_otlp_blob.delay(project_id, key, content_type or "")            # then enqueue
    return batch_id
