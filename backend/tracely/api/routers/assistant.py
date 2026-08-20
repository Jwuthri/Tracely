"""The dashboard's chat widget: conversations, one turn at a time, plus attachments.

Thin by the book — validate, call `assistant_service`, shape the reply. Conversations are scoped
to the project AND to the caller (`Principal.user_id`; None for ingest keys and dev mode, which
then share the project's chats). The LLM call is synchronous (LangChain `create_agent`), so it
runs in a threadpool rather than blocking the event loop for the whole round trip.
"""

from __future__ import annotations

import re
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_principal
from tracely.auth import Principal
from tracely.infrastructure.blob import s3
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.services import assistant_service

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
_ID_RE = re.compile(r"^[0-9a-f]{32}$")  # what we mint — and the only thing we'll look up


class Attachment(BaseModel):
    id: str = Field(max_length=32)
    name: str = Field(max_length=200)
    mime: str = Field(default="application/octet-stream", max_length=100)
    size: int = 0


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    chat_id: str | None = Field(default=None, max_length=36)
    attachments: list[Attachment] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    path: str = Field(default="", max_length=200)  # the page the user is looking at


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    attachments: list[Attachment] = Field(default_factory=list)


def _summary(row) -> dict:
    msgs = row.messages or []
    return {
        "id": row.id,
        "title": row.title or assistant_service.title_for(
            next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
        ),
        "messages": len(msgs),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/assistant/chat")
async def chat(body: ChatBody, principal: Principal = Depends(get_principal)) -> dict:
    """One assistant reply. `{chat_id, title, reply}`, or `{disabled: true}` with no LLM key."""
    try:
        return await run_in_threadpool(
            assistant_service.answer,
            principal.project_id,
            principal.user_id,
            chat_id=body.chat_id,
            message=body.message,
            attachments=[a.model_dump() for a in body.attachments],
            path=body.path,
        )
    except Exception as exc:  # a dead provider is a chat bubble, not a 500 in the console
        log.warning("assistant_chat_failed", project_id=principal.project_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"the model call failed: {exc}"[:300]) from exc


@router.get("/assistant/chats")
async def list_chats(principal: Principal = Depends(get_principal)) -> list[dict]:
    """This caller's conversations, newest first — what the history panel lists."""

    def work():
        with SyncSessionLocal() as s:
            rows = repo.assistant_chat_list(s, principal.project_id, principal.user_id)
            return [_summary(r) for r in rows]

    return await run_in_threadpool(work)


@router.get("/assistant/chats/{chat_id}")
async def get_chat(chat_id: str, principal: Principal = Depends(get_principal)) -> dict:
    """One conversation in full — what reopening it from history loads."""

    def work():
        with SyncSessionLocal() as s:
            row = repo.assistant_chat_get(s, principal.project_id, principal.user_id, chat_id)
            if row is None:
                return None
            return {**_summary(row), "messages": row.messages or []}

    out = await run_in_threadpool(work)
    if out is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return out


@router.delete("/assistant/chats/{chat_id}")
async def delete_chat(chat_id: str, principal: Principal = Depends(get_principal)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            return repo.assistant_chat_delete(s, principal.project_id, principal.user_id, chat_id)

    if not await run_in_threadpool(work):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": True}


@router.post("/assistant/upload")
async def upload(
    file: UploadFile = File(...), principal: Principal = Depends(get_principal)
) -> dict:
    """Store one attachment and hand back the metadata the next message echoes. The bytes go
    under the project's blob prefix, so deleting the workspace takes them along."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    attachment_id = uuid.uuid4().hex
    mime = file.content_type or "application/octet-stream"
    await run_in_threadpool(
        s3.put_blob, s3.assistant_blob_key(principal.project_id, attachment_id), raw, mime
    )
    return {
        "id": attachment_id,
        "name": (file.filename or "file")[:200],
        "mime": mime[:100],
        "size": len(raw),
    }


@router.get("/assistant/files/{attachment_id}")
async def get_file(attachment_id: str, principal: Principal = Depends(get_principal)) -> Response:
    """Serve an attachment back — the thumbnail in the transcript, and the download link.

    Only ever renders images inline. Anything else is handed back as an opaque download: this
    endpoint sits on our own origin, and serving a user-uploaded `text/html` inline with its own
    content type is stored XSS with extra steps.
    """
    if not _ID_RE.match(attachment_id):  # also what keeps a crafted id out of another prefix
        raise HTTPException(status_code=404, detail="not found")
    try:
        raw, mime = await run_in_threadpool(
            s3.get_blob_typed, s3.assistant_blob_key(principal.project_id, attachment_id)
        )
    except Exception:
        raise HTTPException(status_code=404, detail="not found") from None
    inline = mime.startswith("image/") and not mime.endswith("svg+xml")  # SVG executes script
    return Response(
        content=raw,
        media_type=mime if inline else "application/octet-stream",
        headers={
            "Content-Disposition": "inline" if inline else "attachment",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )
