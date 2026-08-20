"""S3 / MinIO blob store. The raw OTLP request body is the source of truth:
the API uploads it BEFORE enqueueing (mirrors Langfuse processEventBatch:
nothing is queued unless the blob is durable). The worker reads it back.
"""

from __future__ import annotations

import boto3
import structlog
from botocore.config import Config

from tracely.config import settings

log = structlog.get_logger()
_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


def put_blob(key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    _s3().put_object(Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=content_type)


def get_blob(key: str) -> bytes:
    return _s3().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def ensure_bucket() -> None:
    """Create the configured bucket if it doesn't exist (idempotent). Run once at deploy/init time —
    a fresh MinIO/S3 host has no bucket (locally the compose `minio-init` service handles it; on
    Railway/managed S3 the backend pre-deploy step calls this)."""
    client = _s3()
    bucket = settings.s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
        return  # already there
    except Exception:
        pass
    try:
        client.create_bucket(Bucket=bucket)
        print(f"created bucket {bucket}")
    except Exception as e:  # race / already-owned / region quirk — tolerate, the bucket exists
        print(f"ensure_bucket({bucket}): {type(e).__name__} — assuming it already exists")


def event_blob_key(project_id: str, batch_id: str, content_type: str) -> str:
    ext = "pb" if "x-protobuf" in content_type else "json"
    return f"{settings.s3_event_prefix}{project_id}/otlp/{batch_id}.{ext}"


def assistant_blob_key(project_id: str, attachment_id: str) -> str:
    """Where a file dropped into the chat widget lives. Under the project's own prefix on
    purpose: `delete_project_blobs` then takes attachments with the workspace, with no second
    list of places customer bytes hide."""
    return f"{settings.s3_event_prefix}{project_id}/assistant/{attachment_id}"


def get_blob_typed(key: str) -> tuple[bytes, str]:
    """Bytes plus the content type they were stored with — what serving a file back needs."""
    obj = _s3().get_object(Bucket=settings.s3_bucket, Key=key)
    return obj["Body"].read(), obj.get("ContentType") or "application/octet-stream"


def delete_project_blobs(project_id: str) -> int:
    """Delete every raw OTLP body this project ever uploaded. Used when a workspace is deleted —
    the blobs are the source of truth, so leaving them behind means the customer's payloads
    outlive the workspace they asked us to remove.

    Best-effort: object storage being unavailable must not block the delete (the rows are already
    gone), so failures are counted as zero rather than raised.
    """
    prefix = f"{settings.s3_event_prefix}{project_id}/"
    client = _s3()
    removed = 0
    try:
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=settings.s3_bucket, Prefix=prefix
        ):
            batch = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if not batch:
                continue
            # delete_objects caps at 1000 keys, which is exactly one page's default maximum.
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": batch})
            removed += len(batch)
    except Exception as exc:
        log.warning("blob_prefix_delete_failed", project_id=project_id, error=str(exc))
    return removed
