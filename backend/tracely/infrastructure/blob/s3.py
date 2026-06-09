"""S3 / MinIO blob store. The raw OTLP request body is the source of truth:
the API uploads it BEFORE enqueueing (mirrors Langfuse processEventBatch:
nothing is queued unless the blob is durable). The worker reads it back.
"""

from __future__ import annotations

import boto3
from botocore.config import Config

from tracely.config import settings

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
