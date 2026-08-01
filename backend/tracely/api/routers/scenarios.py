"""Emulated conversations: scenario CRUD, import-from-trace, and the agent endpoint config.

Pure HTTP shaping — Postgres access goes through `infrastructure.db.repositories`, ClickHouse
reads through `async_reader`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.domain.simulation import Turn, normalize_turns, serialize_turns, user_text
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Agent, AgentEndpoint, Scenario
from tracely.infrastructure.llm.provider import encrypt_secret
from tracely.services.gate_service import GateService

router = APIRouter(prefix="/api")


def _scenario_dict(sc: Scenario, agent_slug: str | None = None) -> dict[str, Any]:
    return {
        "id": sc.id,
        "agent_id": sc.agent_id,
        # `tracely simulate --all` gates every agent that has an enabled scenario, and it discovers
        # them from this list — so the slug has to travel with the row, not just the opaque id.
        "agent": agent_slug,
        "title": sc.title,
        "kind": sc.kind,
        # Always the normalized `{message, expect, tools}` shape, so the UI has one thing to
        # render whether the row was authored before expectations existed or after.
        "turns": serialize_turns(normalize_turns(sc.turns)),
        "goal": sc.goal,
        "max_turns": sc.max_turns,
        "source_thread_id": sc.source_thread_id,
        "enabled": sc.enabled,
        "created_at": sc.created_at.isoformat() if sc.created_at else None,
    }


def _slug(s, agent_id: str) -> str | None:
    a = s.get(Agent, agent_id)
    return a.slug if a else None


def _resolve_agent(s, project_id: str, agent_ref: str) -> str:
    aid = GateService(s).resolve_agent_id(project_id, agent_ref)
    if not aid:
        raise HTTPException(status_code=404, detail=f"agent '{agent_ref}' not found")
    return aid


# ── scenarios ─────────────────────────────────────────────────────────────────


@router.get("/scenarios")
async def list_scenarios(agent: str | None = None, project_id: str = Depends(get_project_id)):
    def work():
        with SyncSessionLocal() as s:
            aid = _resolve_agent(s, project_id, agent) if agent else None
            slugs = {a.id: a.slug for a in repo.agents_list(s, project_id)}
            return [
                _scenario_dict(sc, slugs.get(sc.agent_id))
                for sc in repo.scenarios_list(s, project_id, aid)
            ]

    return await run_in_threadpool(work)


@router.post("/scenarios")
async def create_scenario(project_id: str = Depends(get_project_id), body: dict = Body(...)):
    """Author a conversation directly. `SCRIPTED` needs `turns`; `ADVERSARIAL` needs a `goal`."""
    kind = (body.get("kind") or "SCRIPTED").upper()
    turns = normalize_turns(body.get("turns") or [])
    goal = (body.get("goal") or "").strip()
    if kind == "SCRIPTED" and not turns:
        raise HTTPException(status_code=400, detail="a SCRIPTED scenario needs at least one turn")
    if kind == "ADVERSARIAL" and not goal:
        raise HTTPException(status_code=400, detail="an ADVERSARIAL scenario needs a goal")
    if not body.get("agent"):
        raise HTTPException(status_code=400, detail="agent required")

    def work():
        with SyncSessionLocal() as s:
            aid = _resolve_agent(s, project_id, body["agent"])
            sc = Scenario(
                id=str(uuid.uuid4()), project_id=project_id, agent_id=aid,
                title=(body.get("title") or "").strip()[:512], kind=kind,
                turns=serialize_turns(turns), goal=goal,
                max_turns=int(body.get("max_turns") or 6),
                source_thread_id=body.get("source_thread_id") or "",
                enabled=bool(body.get("enabled", True)),
            )
            s.add(sc)
            s.commit()
            return _scenario_dict(sc, _slug(s, sc.agent_id))

    return await run_in_threadpool(work)


@router.post("/scenarios/import")
async def import_scenario(project_id: str = Depends(get_project_id), body: dict = Body(...)):
    """Turn a real conversation into a scenario: read the thread's turns and store the user side
    verbatim. The conversation that broke in production becomes the one that gates the PR
    claiming to fix it."""
    thread_id = body.get("thread_id")
    if not thread_id or not body.get("agent"):
        raise HTTPException(status_code=400, detail="thread_id and agent required")

    turns = await async_reader.session_turns(project_id, thread_id)
    messages = [user_text(str(t.get("input") or "")) for t in turns]
    messages = [m for m in messages if m]
    if not messages:
        raise HTTPException(status_code=400, detail=f"thread '{thread_id}' has no user input")

    def work():
        with SyncSessionLocal() as s:
            aid = _resolve_agent(s, project_id, body["agent"])
            sc = Scenario(
                id=str(uuid.uuid4()), project_id=project_id, agent_id=aid,
                title=(body.get("title") or f"Imported · {messages[0][:80]}")[:512],
                kind="SCRIPTED", turns=serialize_turns([Turn(message=m) for m in messages]),
                max_turns=len(messages),
                source_thread_id=thread_id, created_by="import",
            )
            s.add(sc)
            s.commit()
            return _scenario_dict(sc, _slug(s, sc.agent_id))

    return await run_in_threadpool(work)


@router.patch("/scenarios/{scenario_id}")
async def update_scenario(
    scenario_id: str, project_id: str = Depends(get_project_id), body: dict = Body(...)
):
    """Edit a scenario. Partial: only the keys present are touched, so the enable/disable toggle
    can send `{"enabled": false}` alone.

    Holds the same invariants as create, against the *resulting* row rather than the payload — a
    scenario edited down to zero turns would still run, produce nothing, and land as a SKIP that
    quietly stops protecting anything.
    """
    def work():
        with SyncSessionLocal() as s:
            sc = s.get(Scenario, scenario_id)
            if not sc or sc.project_id != project_id:
                return ("missing", None)
            for field in ("title", "goal", "source_thread_id"):
                if field in body:
                    setattr(sc, field, str(body[field]).strip())
            if "kind" in body:
                kind = str(body["kind"]).upper()
                if kind not in ("SCRIPTED", "ADVERSARIAL"):
                    return ("bad", "kind must be SCRIPTED or ADVERSARIAL")
                sc.kind = kind
            if "turns" in body:
                sc.turns = serialize_turns(normalize_turns(body["turns"] or []))
            if "max_turns" in body:
                sc.max_turns = max(1, int(body["max_turns"]))
            if "enabled" in body:
                sc.enabled = bool(body["enabled"])

            if sc.kind == "SCRIPTED" and not sc.turns:
                return ("bad", "a SCRIPTED scenario needs at least one turn")
            if sc.kind == "ADVERSARIAL" and not (sc.goal or "").strip():
                return ("bad", "an ADVERSARIAL scenario needs a goal")

            s.commit()
            return ("ok", _scenario_dict(sc, _slug(s, sc.agent_id)))

    status, payload = await run_in_threadpool(work)
    if status == "missing":
        raise HTTPException(status_code=404, detail="scenario not found")
    if status == "bad":
        raise HTTPException(status_code=400, detail=payload)
    return payload


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str, project_id: str = Depends(get_project_id)):
    def work():
        with SyncSessionLocal() as s:
            return repo.scenario_delete(s, project_id, scenario_id)

    if not await run_in_threadpool(work):
        raise HTTPException(status_code=404, detail="scenario not found")
    return {"deleted": scenario_id}


# ── endpoint config ───────────────────────────────────────────────────────────


@router.get("/agents/{agent_ref}/endpoint")
async def get_endpoint(agent_ref: str, project_id: str = Depends(get_project_id)):
    """The endpoint config. The token is never returned — only whether one is set."""
    def work():
        with SyncSessionLocal() as s:
            aid = _resolve_agent(s, project_id, agent_ref)
            ep = s.get(AgentEndpoint, aid)
            if not ep:
                return {"agent_id": aid, "configured": False}
            return {
                "agent_id": aid, "configured": True, "url": ep.url,
                "auth_header": ep.auth_header, "auth_scheme": ep.auth_scheme,
                "has_token": bool(ep.token_encrypted), "reply_path": ep.reply_path,
                "session_key": ep.session_key, "timeout_s": ep.timeout_s,
                "extra_headers": ep.extra_headers or {}, "extra_body": ep.extra_body or {},
            }

    return await run_in_threadpool(work)


@router.put("/agents/{agent_ref}/endpoint")
async def set_endpoint(
    agent_ref: str, project_id: str = Depends(get_project_id), body: dict = Body(...)
):
    """Register where Tracely should call this agent. `token` is write-only: encrypted at rest
    and never echoed back. Omit it on an update to keep the stored one."""
    url = (body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    token = (body.get("token") or "").strip()
    try:
        encrypted = encrypt_secret(token) if token else ""
    except RuntimeError as exc:  # SECRETS_ENCRYPTION_KEY unset — never store the token in clear
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Both are spread into the request (`**extra_body`, `**extra_headers`), so a non-object here
    # would blow up mid-conversation on the worker. Reject at the edge instead.
    for name in ("extra_body", "extra_headers"):
        value = body.get(name)
        if value is not None and not isinstance(value, dict):
            raise HTTPException(status_code=400, detail=f"{name} must be a JSON object")
    if any(not isinstance(v, str) for v in (body.get("extra_headers") or {}).values()):
        raise HTTPException(status_code=400, detail="extra_headers values must be strings")

    def work():
        with SyncSessionLocal() as s:
            aid = _resolve_agent(s, project_id, agent_ref)
            ep = s.get(AgentEndpoint, aid) or AgentEndpoint(agent_id=aid, project_id=project_id)
            ep.url = url
            ep.auth_header = (body.get("auth_header") or "Authorization")[:64]
            ep.auth_scheme = body.get("auth_scheme", "Bearer")[:32]
            ep.reply_path = (body.get("reply_path") or "")[:200]
            ep.session_key = body.get("session_key", "conversation_id")[:120]
            ep.timeout_s = int(body.get("timeout_s") or 60)
            ep.extra_headers = body.get("extra_headers") or {}
            ep.extra_body = body.get("extra_body") or {}
            if encrypted:
                ep.token_encrypted = encrypted
            s.add(ep)
            s.commit()
            return {"agent_id": aid, "url": ep.url, "has_token": bool(ep.token_encrypted)}

    return await run_in_threadpool(work)
