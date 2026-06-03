"""OTLP/HTTP traces endpoint. Blob-first ingestion then enqueue (see process_batch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.ingestion import ingest_otlp

router = APIRouter()


@router.post("/v1/traces")
async def otlp_traces(request: Request, project_id: str = Depends(get_project_id)) -> Response:
    raw = await request.body()
    content_type = request.headers.get("content-type", "application/x-protobuf")
    # ingest_otlp does sync S3 put + Celery enqueue -> offload from the event loop
    await run_in_threadpool(ingest_otlp, project_id, content_type, raw)
    # OTLP success = 200 with an (empty) ExportTraceServiceResponse
    return Response(status_code=200, media_type="application/x-protobuf", content=b"")
