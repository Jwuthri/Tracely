"""Public conversation share links.

A share token is a signed, read-only capability for exactly ONE conversation. It is verified HERE,
by `verify_share`, and never passed to `resolve_principal` — routing it through the normal auth path
would turn a share link into a full project read key. That is the whole security argument for this
module: the anonymous endpoint touches no auth dependency, and the token's own claims supply the
`project_id` scope that every reader call still requires.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tracely.api.advisory import advisory_score_names
from tracely.api.auth import get_project_id
from tracely.auth.tokens import SHARE_TTL_SECONDS, TokenError, issue_share, verify_share
from tracely.domain.evaluation.verdict import rollup_verdict
from tracely.infrastructure.clickhouse import async_reader

router = APIRouter(prefix="/api")


class ShareBody(BaseModel):
    thread_id: str


@router.post("/share")
async def create_share(body: ShareBody, project_id: str = Depends(get_project_id)) -> dict:
    """Mint a public link for a conversation. Minting again returns a fresh token with a new
    expiry; previously issued tokens keep working until theirs runs out (see the note in
    `auth/tokens.py` — there is no revoke without a revocation table)."""
    thread_id = body.thread_id.strip()
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id required")
    return {
        "token": issue_share(project_id, thread_id),
        "expires_in": SHARE_TTL_SECONDS,
    }


@router.get("/share/{token}")
async def read_share(token: str) -> dict:
    """Anonymous read of a shared conversation — NO auth dependency, by design.

    Every failure is a 404, never a 401/403: an invalid, expired, or foreign token must not let a
    stranger distinguish "wrong link" from "real conversation you can't see"."""
    try:
        project_id, thread_id = verify_share(token)
    except TokenError:
        raise HTTPException(status_code=404, detail="link expired or invalid") from None

    advisory = await advisory_score_names(project_id)
    turns = await async_reader.session_turns(project_id, thread_id, advisory)
    if not turns:
        raise HTTPException(status_code=404, detail="link expired or invalid")

    by_trace = await async_reader.scores_by_trace(project_id, [t["trace_id"] for t in turns])
    # Spans in parallel, same as the authed page does with Promise.all over getTrace.
    spans = await asyncio.gather(
        *(async_reader.trace_spans(project_id, t["trace_id"]) for t in turns)
    )
    for t, t_spans in zip(turns, spans, strict=True):
        t["scores"] = by_trace.get(t["trace_id"], [])
        t["verdict"] = rollup_verdict(t["scores"], advisory)
        t["spans"] = t_spans

    return {
        "thread_id": thread_id,
        "turns": turns,
        "scores": await async_reader.conversation_scores(project_id, thread_id),
    }
