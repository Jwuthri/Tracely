"""FastAPI wrapper so Tracely scenarios can DRIVE these demo agents over HTTP.

    Tracely scenario ──POST /chat──▶ this server ──▶ the agent ──▶ {"reply": ...}

Tracely mints the trace id and sends it as a W3C `traceparent` header; `tracely.trace(...,
traceparent=...)` joins it, so the agent's own tool/generation spans nest under the turn instead
of landing on a disconnected trace. That is the whole point — it lets a scenario's step-level and
adversarial evaluators grade the real trajectory, not just request-in / reply-out.

One framework per process, chosen with DEMO (default langgraph) — importing only that module keeps
its auto-instrumentor the only one active:

    DEMO=langgraph uv run uvicorn server:app --port 8100
    DEMO=openai    uv run uvicorn server:app --port 8101   # needs OPENAI_API_KEY
    DEMO=anthropic uv run uvicorn server:app --port 8102   # needs ANTHROPIC_API_KEY

Then in Tracely: Scenarios → pick the agent → register `http://host.docker.internal:8100/chat`
as its endpoint (use `host.docker.internal` if Tracely runs in Docker and the server on the host),
and Run a scenario. No reply-path config needed — `{"reply": ...}` is one of the shapes Tracely
extracts out of the box.
"""

from __future__ import annotations

import importlib
import inspect
import os

import tracely_sdk as tracely
from fastapi import FastAPI, Request

import shared

_MODULES = {
    "langgraph": "demo_langgraph",
    "openai": "demo_openai_agents",
    "anthropic": "demo_anthropic",
}
DEMO = os.environ.get("DEMO", "langgraph").lower()
if DEMO not in _MODULES:
    raise SystemExit(f"DEMO must be one of {sorted(_MODULES)} (got {DEMO!r})")

# Importing the module runs its `tracely.init()` + auto-instrumentor and builds the agents.
demo = importlib.import_module(_MODULES[DEMO])

app = FastAPI(title=f"Nimbus support desk · {DEMO}")


@app.post("/chat")
async def chat(body: dict, request: Request) -> dict:
    """One turn. Tracely POSTs `{messages, message, conversation_id}` and a `traceparent` header."""
    messages = body.get("messages") or []
    message = body.get("message") or (messages[-1].get("content", "") if messages else "")
    history = messages[:-1]  # everything before this turn's user message
    conversation = body.get("conversation_id") or "sim"

    with tracely.trace(
        agent=demo.AGENT,
        conversation=conversation,
        user=shared.CUSTOMER,
        traceparent=request.headers.get("traceparent"),
        agents=demo.CATALOG,
    ):
        answer = demo.reply(message, history, conversation)
        if inspect.isawaitable(answer):  # openai-agents' reply is async
            answer = await answer
    return {"reply": answer}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "demo": DEMO, "agent": demo.AGENT}
