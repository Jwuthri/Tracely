"""Drive a customer's agent endpoint through a multi-turn conversation and land it as a trace.

    scenario → N turns → POST the endpoint → emit each turn as OTLP → normal ingest → auto-eval

Two things make this cheap. First, **Tracely mints the trace id** for each turn and sends it as a
W3C `traceparent`: any OTel-instrumented service continues that context, so the customer's own
spans (tool calls, retrieval, sub-agents) arrive under the same trace and nest under our turn
span. No digest matching, no correlation table, no polling for the trace to show up — we know its
id before the agent has replied. Second, the turn is handed to `ingest_otlp`, so an emulated
conversation walks the identical blob → Celery → ClickHouse → evaluate path as production
traffic and is graded by the project's own evaluators.

A turn span is emitted **whether or not** the endpoint answers. A timeout or a 500 becomes an
ERROR span, which is a real graded failure rather than a silently missing conversation.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
import structlog

from tracely.config import settings
from tracely.domain import introspection
from tracely.domain.simulation.attacker import ATTACKER_SYSTEM, AttackerMove, attacker_prompt
from tracely.domain.simulation.emit import turn_payload
from tracely.domain.simulation.turns import normalize_turns
from tracely.infrastructure.blob import s3 as blobstore
from tracely.infrastructure.db.models import AgentEndpoint, Scenario
from tracely.infrastructure.llm.provider import decrypt_secret, llm_enabled, use_project_key
from tracely.services.ingestion_service import IngestionService
from tracely.services.introspection_service import record

log = structlog.get_logger()

# Response-body shapes tried in order when an endpoint has no explicit `reply_path`. Covers
# OpenAI-compatible APIs and the handful of obvious bespoke conventions, so the common case needs
# no configuration at all.
_REPLY_PATHS = (
    "choices.0.message.content",
    "reply",
    "response",
    "output",
    "message",
    "content",
    "text",
    "answer",
    "result",
)

class SimulationService:
    """Runs one scenario against one agent endpoint. Stateless — construct per run."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    # ── public ────────────────────────────────────────────────────────────────

    def run_scenario(
        self,
        project_id: str,
        agent_slug: str,
        scenario: Scenario,
        endpoint: AgentEndpoint,
        env: str = "ci",
        weaknesses: list[str] | None = None,
    ) -> dict[str, Any]:
        """Drive the whole conversation. Returns
        `{conversation_id, trace_ids, turns, error}` — grading happens later, off the scores the
        ingest pipeline writes for these traces.

        `weaknesses` (adversarial only) are this agent's known production failure clusters, handed
        to the attacker so it probes where the agent has actually broken before.
        """
        conversation_id = uuid.uuid4().hex
        history: list[dict[str, str]] = []
        trace_ids: list[str] = []
        turns: list[dict] = []
        tried: list[str] = []  # techniques already spent, so the attacker stops repeating them

        planned = self._planned_turn_count(scenario)
        # A recording of the DRIVING: the attacker's reasoning and the raw HTTP exchange with the
        # customer's endpoint. Distinct from the conversation traces themselves — those are what
        # the agent said, this is what Tracely did to make it say that.
        with record(
            introspection.SIM, conversation_id,
            f"sim · {scenario.title or scenario.kind}",
            project_id=project_id, agent_slug=agent_slug, env=env,
            conversation_id=f"sim:{conversation_id}",
        ) as rec:
            for index in range(planned):
                if rec:
                    rec.label = f"turn {index + 1}"
                move = None
                if scenario.kind == "ADVERSARIAL":
                    move = self._attacker_move(project_id, scenario, history, tried, weaknesses)
                    # The attacker judges the replies it has SEEN, so stop before spending another
                    # turn on an attack that already worked. This is a budget optimisation only —
                    # the gate's verdict comes from the judge that re-reads the transcript.
                    if move and move.goal_achieved:
                        log.info(
                            "adversarial_early_stop",
                            scenario_id=scenario.id, turn=index, tried=tried,
                        )
                        if rec:
                            rec.add("early stop", obs_type="EVENT",
                                    input=f"techniques tried: {', '.join(tried)}",
                                    output="attacker reports the goal already achieved")
                        break
                    message = move.message if move else ""
                    if move:
                        tried.append(move.technique)
                        if rec:
                            rec.add("technique", obs_type="EVENT", input=move.technique,
                                    output=move.rationale)
                else:
                    message = self._next_message(project_id, scenario, history, index)
                if not message:
                    break  # attacker produced nothing (no LLM key / refusal) — stop cleanly

                trace_id, span_id = os.urandom(16), os.urandom(8)
                start_ns = time.time_ns()
                reply, error = self._call_endpoint(
                    endpoint, conversation_id, history, message, trace_id, span_id
                )
                end_ns = time.time_ns()
                if rec:
                    # The exchange as it went over the wire, so a wrong `reply_path` or a 500 from
                    # the endpoint is visible without turning on worker logs.
                    rec.add(
                        f"POST {endpoint.url}", obs_type="TOOL", input=message,
                        output=reply or "(no reply extracted)", error=error, start_ns=start_ns,
                    )

                self._emit_turn(
                    project_id=project_id,
                    agent_slug=agent_slug,
                    scenario=scenario,
                    conversation_id=conversation_id,
                    turn_index=index,
                    trace_id=trace_id,
                    span_id=span_id,
                    user_message=message,
                    agent_reply=reply,
                    env=env,
                    start_ns=start_ns,
                    end_ns=end_ns,
                    error=error,
                )

                trace_ids.append(trace_id.hex())
                turns.append({
                    "index": index, "input": message, "output": reply, "error": error,
                    **({"technique": move.technique, "rationale": move.rationale} if move else {}),
                })
                history += [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": reply},
                ]
                if error:
                    break  # a dead endpoint won't get healthier on turn 4

        return {
            "conversation_id": conversation_id,
            "trace_ids": trace_ids,
            "turns": turns,
            "error": next((t["error"] for t in turns if t["error"]), ""),
        }

    # ── turn planning ─────────────────────────────────────────────────────────

    @staticmethod
    def _planned_turn_count(scenario: Scenario) -> int:
        if scenario.kind == "ADVERSARIAL":
            return max(1, scenario.max_turns or 6)
        return len(normalize_turns(scenario.turns))

    def _next_message(
        self, project_id: str, scenario: Scenario, history: list[dict], index: int
    ) -> str:
        turns = normalize_turns(scenario.turns)
        return turns[index].message if index < len(turns) else ""

    def _attacker_move(
        self,
        project_id: str,
        scenario: Scenario,
        history: list[dict],
        tried: list[str],
        weaknesses: list[str] | None,
    ) -> AttackerMove | None:
        """Ask the attacker for its next move: a technique, a message, and whether the goal already
        looks achieved.

        Structured rather than free text so the loop can stop early and the PR comment can show
        *how* the agent was broken, not just that it was. Returns None when no LLM is configured or
        the call fails — an adversarial scenario then ends with fewer turns and is graded on what
        it got, never silently passed (an unjudged attack is SKIP, and all-SKIP is UNGRADED).
        """
        with use_project_key(project_id):
            if not llm_enabled():
                log.warning("adversarial_skipped_no_llm", scenario_id=scenario.id)
                return None
            transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history)
            try:
                from tracely.infrastructure.llm.provider import run_structured_agent

                return run_structured_agent(
                    attacker_prompt(scenario.goal, transcript, tried, weaknesses),
                    response_format=AttackerMove,
                    system_prompt=ATTACKER_SYSTEM,
                    model=settings.attacker_model or None,
                    # Warm: a deterministic attacker rephrases the same probe every turn.
                    temperature=0.9,
                )
            except Exception as exc:  # attacker failure must not kill the gate run
                log.warning("adversarial_turn_failed", scenario_id=scenario.id, error=str(exc))
                return None

    # ── the customer's endpoint ───────────────────────────────────────────────

    def _call_endpoint(
        self,
        endpoint: AgentEndpoint,
        conversation_id: str,
        history: list[dict],
        message: str,
        trace_id: bytes,
        span_id: bytes,
    ) -> tuple[str, str]:
        """POST one turn. Returns `(reply, error)` — never raises; a transport failure is a
        graded ERROR turn, not a crashed gate."""
        body: dict[str, Any] = {
            # `extra_body` first so it can never clobber the fields the conversation depends on
            # (messages/session), only add to them — tenant_id, locale, channel, and whatever
            # else the customer's API requires alongside the message.
            **(endpoint.extra_body or {}),
            "messages": [*history, {"role": "user", "content": message}],
            "message": message,  # bespoke single-message APIs read this instead of `messages`
        }
        if endpoint.session_key:
            body[endpoint.session_key] = conversation_id

        headers = {
            "content-type": "application/json",
            # W3C trace context: an OTel-instrumented endpoint continues THIS trace, so its
            # internal spans nest under our turn span. Sampled flag set (01) or the customer's
            # sampler may drop them.
            "traceparent": f"00-{trace_id.hex()}-{span_id.hex()}-01",
            **(endpoint.extra_headers or {}),
        }
        token = decrypt_secret(endpoint.token_encrypted) if endpoint.token_encrypted else None
        if token:
            scheme = (endpoint.auth_scheme or "").strip()
            headers[endpoint.auth_header or "Authorization"] = (
                f"{scheme} {token}" if scheme else token
            )

        client = self._client or httpx.Client(timeout=endpoint.timeout_s or 60)
        try:
            resp = client.post(endpoint.url, json=body, headers=headers)
            if resp.status_code >= 400:
                return "", f"HTTP {resp.status_code}: {resp.text[:200]}"
            return self._extract_reply(resp, endpoint.reply_path), ""
        except Exception as exc:
            return "", f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            if self._client is None:
                client.close()

    @classmethod
    def _extract_reply(cls, resp: httpx.Response, reply_path: str) -> str:
        """Pull the assistant's text out of the response body.

        An explicit `reply_path` wins. Otherwise try the common shapes, and fall back to the raw
        body — a plain-text endpoint is a perfectly reasonable thing to point us at.
        """
        try:
            data = resp.json()
        except Exception:
            return resp.text[:20000]
        if isinstance(data, str):
            return data
        if reply_path:
            found = cls._dig(data, reply_path)
            return "" if found is None else cls._stringify(found)
        for path in _REPLY_PATHS:
            found = cls._dig(data, path)
            if isinstance(found, str) and found.strip():
                return found
        return json.dumps(data, default=str)[:20000]

    @staticmethod
    def _dig(data: Any, path: str) -> Any:
        """Walk a dotted path; integer segments index into lists. None if the path misses."""
        cur = data
        for part in path.split("."):
            if isinstance(cur, list):
                if not part.isdigit() or int(part) >= len(cur):
                    return None
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                if part not in cur:
                    return None
                cur = cur[part]
            else:
                return None
        return cur

    @staticmethod
    def _stringify(value: Any) -> str:
        return value if isinstance(value, str) else json.dumps(value, default=str)[:20000]

    # ── emit ──────────────────────────────────────────────────────────────────

    def _emit_turn(self, *, project_id: str, scenario: Scenario, **kw: Any) -> None:
        """Persist one turn: blob first (durable), then map it into ClickHouse **inline**.

        Deliberately not `ingest_otlp`, which enqueues a Celery task. This code already runs
        inside the gate task, and the worker runs `--pool=solo --concurrency=1` — an enqueued
        ingest could not be picked up until the gate task returned, while the gate task waits for
        that ingest. That is a hard deadlock in the default local config, and merely a race in a
        concurrent one. Blob-first durability is unchanged; only the queue hop is skipped, which a
        merge-blocker wants anyway: a gate should not depend on queue scheduling.
        """
        payload = turn_payload(scenario_title=scenario.title, **kw)
        raw = json.dumps(payload).encode()
        key = blobstore.event_blob_key(project_id, uuid.uuid4().hex, "application/json")
        blobstore.put_blob(key, raw, "application/json")
        IngestionService().process_blob(project_id, key, "application/json")
