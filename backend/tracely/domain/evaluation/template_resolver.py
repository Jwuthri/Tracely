"""`@VARIABLE` template resolution for Advanced-mode LLM-judge evaluators.

A basic judge gets its context **auto-injected** (request / answer / tool results / transcript /
step I/O). Advanced mode hands that control to the user: they write the rubric with `@VARIABLE`
placeholders that are resolved against the real trace/thread data at run time, deciding exactly
what the judge reads.

Three pieces:
- `TEMPLATE_VARIABLES` — the catalog (UI / autocomplete metadata): name, description, type,
  applicable levels, nested object props. Mirrored in `frontend/app/lib/templateVariables.ts`.
- `build_context(...)` — turns already-fetched span dicts into an `EvaluationContext` for a level.
  **Pure** (no I/O), and materializes ONLY the referenced vars (`wanted_vars`) so an unused
  `@HISTORY`/`@LIST_AGENT` costs nothing in the grading hot path.
- `TemplateResolver.resolve(...)` — substitutes every `@NAME` / `@NAME.prop` match; a value that
  isn't present becomes the literal `[No <REF> available]` (soft miss — never an error, never
  blocks a grade).

The same builder + resolver power both the run path (`LLMJudgeEvaluator`, sync spans) and the
preview endpoint (async spans), so "what you preview" matches "what runs".

Level / type constants are duplicated here as plain strings (mirroring
`evaluators/base.py`) rather than imported, to avoid triggering the `evaluators` package import
(which registers the judge, which imports this module).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from tracely.domain.evaluation.text import answer_for, content_text, first_io
from tracely.domain.traces.spans import root_span

# Mirrors evaluators/base.py + the ingest vocabulary (otel/types.py). Local copies dodge an
# import cycle (base → registers the judge → imports this module).
CONVERSATION = "CONVERSATION"
RUN = "AGENT_RUN"
SPAN = "SPAN"
TOOL = "TOOL"
GENERATION = "GENERATION"
CHAIN = "CHAIN"
THINKING = "THINKING"

# Catalog levels (coarser than evaluator levels): every step-flavored evaluator level maps to
# "step", AGENT_RUN to "message", CONVERSATION to "conversation".
CL_CONVERSATION = "conversation"
CL_MESSAGE = "message"
CL_STEP = "step"

# Group 1 = UPPERCASE variable name, group 2 = optional lowercase `.property`. The SAME regex is
# used to extract (here + the frontend) and to resolve. Case matters: `email@x.com` / lowercase
# `@foo` are NOT variables.
VARIABLE_RE = re.compile(r"@([A-Z_]+)(?:\.([a-z_]+))?")

_HISTORY_CLIP = 8000  # whole-transcript budget (matches the basic judge's transcript clip)
_MSG_CLIP = 2000  # per user/assistant message
_STEP_CLIP = 2000  # per step field
_STRUCT_CLIP = 4000  # @CURRENT_STEP.output_structured — generous (the user asked to inspect it)


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


# ── catalog (UI metadata; not on the grading hot path) ───────────────────────


@dataclass(frozen=True)
class TemplateVariable:
    name: str
    description: str
    type: str  # "string" | "object"
    levels: tuple[str, ...]  # catalog levels that expose it
    props: tuple[tuple[str, str], ...] = ()  # (prop, description) for object vars
    sequential_only: bool = False  # only meaningful when execution_mode == "sequential"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "levels": list(self.levels),
            "props": [{"name": n, "description": d} for n, d in self.props],
            "sequential_only": self.sequential_only,
        }


_ALL = (CL_CONVERSATION, CL_MESSAGE, CL_STEP)
_STEP_PROPS = (
    ("tool_call", "The tool invocation (name + arguments) at this step"),
    ("tool_result", "The tool's returned result"),
    ("thinking", "The step's reasoning/thinking text (THINKING steps)"),
    ("output_content", "The readable text output of the step"),
    ("output_structured", "The raw structured (JSON) output of the step"),
)

TEMPLATE_VARIABLES: tuple[TemplateVariable, ...] = (
    # common (all levels)
    TemplateVariable("HISTORY", "Full formatted conversation history", "string", _ALL),
    TemplateVariable("GOAL", "User's overall goal/intent (first request in the thread)", "string", _ALL),
    TemplateVariable("LIST_AGENT", "List of agents seen with the tools they called", "string", _ALL),
    # conversation only
    TemplateVariable("MESSAGES", "All turns formatted ([role]: text)", "string", (CL_CONVERSATION,)),
    TemplateVariable("USER_MESSAGES", "All user requests only", "string", (CL_CONVERSATION,)),
    TemplateVariable("ASSISTANT_MESSAGES", "All assistant answers only", "string", (CL_CONVERSATION,)),
    TemplateVariable("FIRST_USER_MSG", "The first user request", "string", (CL_CONVERSATION,)),
    TemplateVariable("LAST_USER_MSG", "The last user request", "string", (CL_CONVERSATION,)),
    TemplateVariable("LAST_ASSISTANT_MSG", "The last assistant answer", "string", (CL_CONVERSATION,)),
    # message level (step inherits)
    TemplateVariable("PREVIOUS_USER_MSG", "The previous turn's user request", "string", (CL_MESSAGE, CL_STEP)),
    TemplateVariable("PREVIOUS_ASSISTANT_MSG", "The previous turn's assistant answer", "string", (CL_MESSAGE, CL_STEP)),
    TemplateVariable(
        "CURRENT_MESSAGE", "The turn under evaluation", "object", (CL_MESSAGE, CL_STEP),
        props=(("input", "The user request"), ("output", "The assistant answer"), ("role", "Always 'assistant'")),
    ),
    TemplateVariable("CURRENT_STEPS", "All steps of the current turn, formatted", "string", (CL_MESSAGE, CL_STEP)),
    TemplateVariable("CURRENT_STEPS_COUNT", "Number of steps in the current turn", "string", (CL_MESSAGE, CL_STEP)),
    # step only
    TemplateVariable("PREVIOUS_STEP", "The previous step in this turn", "object", (CL_STEP,), props=_STEP_PROPS),
    TemplateVariable("CURRENT_STEP", "The step under evaluation", "object", (CL_STEP,), props=_STEP_PROPS),
    TemplateVariable("STEP_NUMBER", "1-indexed position of the current step", "string", (CL_STEP,)),
    # sequential mode only (message + step)
    TemplateVariable(
        "METRIC_PREVIOUS_RESULT", "The previous item's result of this metric (sequential mode)",
        "string", (CL_MESSAGE, CL_STEP), sequential_only=True,
    ),
)

_BY_NAME = {v.name: v for v in TEMPLATE_VARIABLES}


def catalog_level(level: str) -> str:
    """Map an evaluator level (CONVERSATION / AGENT_RUN / SPAN / TOOL / …) to a catalog level."""
    upper = (level or "").upper()
    if upper == CONVERSATION:
        return CL_CONVERSATION
    if upper in (RUN, "RUN", "MESSAGE"):
        return CL_MESSAGE
    return CL_STEP


def variables_for_level(level: str) -> list[TemplateVariable]:
    cl = catalog_level(level)
    return [v for v in TEMPLATE_VARIABLES if cl in v.levels]


def variables_for_level_json(level: str) -> list[dict[str, Any]]:
    """The level's variables as JSON — drives the discovery endpoint + the editor's count."""
    return [v.to_json() for v in variables_for_level(level)]


def extract_template_variables(prompt: str) -> list[str]:
    """De-duplicated list of refs used in `prompt` (e.g. ['HISTORY', 'CURRENT_STEP.tool_call'])."""
    out: list[str] = []
    for m in VARIABLE_RE.finditer(prompt or ""):
        ref = m.group(1) + (f".{m.group(2)}" if m.group(2) else "")
        if ref not in out:
            out.append(ref)
    return out


def _base_names(refs: list[str] | None) -> set[str] | None:
    """The bare variable names (drop `.prop`) referenced — drives lazy context materialization."""
    if refs is None:
        return None
    return {r.split(".", 1)[0] for r in refs}


# ── resolution context (one bundle per evaluated item) ───────────────────────


@dataclass
class EvaluationContext:
    """Everything a template might reference for ONE evaluated item. A `None` field is treated as
    "not present" → the resolver renders `[No <REF> available]`. Built by `build_context`."""

    history: str | None = None
    goal: str | None = None
    agents: str | None = None
    messages: str | None = None
    user_messages: str | None = None
    assistant_messages: str | None = None
    first_user_msg: str | None = None
    last_user_msg: str | None = None
    last_assistant_msg: str | None = None
    previous_user_msg: str | None = None
    previous_assistant_msg: str | None = None
    current_message: dict[str, Any] | None = None  # {input, output, role}
    current_steps: str | None = None
    current_steps_count: str | None = None
    previous_step: dict[str, Any] | None = None  # a span dict
    current_step: dict[str, Any] | None = None  # a span dict
    step_number: str | None = None
    metric_previous_result: dict[str, Any] | None = None


@dataclass
class ResolvedTemplate:
    resolved_text: str
    variables_used: list[str] = field(default_factory=list)
    variables_missing: list[str] = field(default_factory=list)


# ── span / turn formatters ───────────────────────────────────────────────────


def _turn_io(spans: list[dict]) -> tuple[str, str]:
    """A turn's (user request, assistant answer) from its spans."""
    root = root_span(spans)
    user = content_text(root.get("input")) or first_io(spans, "input")
    answer = answer_for(root, spans, TOOL, GENERATION, CHAIN)
    return user, answer


def _group_turns(thread_spans: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group spans into turns by `trace_id`, preserving first-seen order (spans arrive ordered by
    start_time, so the first time a trace_id appears is its position in the thread)."""
    by_trace: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in thread_spans:
        tid = s.get("trace_id") or ""
        if tid not in by_trace:
            by_trace[tid] = []
            order.append(tid)
        by_trace[tid].append(s)
    return [(tid, by_trace[tid]) for tid in order]


def _format_agents(spans: list[dict]) -> str | None:
    by_agent: dict[str, set[str]] = {}
    for s in spans:
        aid = s.get("agent_id") or ""
        if not aid:
            continue
        tools = by_agent.setdefault(aid, set())
        if s.get("type") == TOOL and s.get("name"):
            tools.add(str(s["name"]))
        for t in s.get("tool_call_names") or []:
            if t:
                tools.add(str(t))
    if not by_agent:
        return None
    lines = []
    for aid, tools in by_agent.items():
        lines.append(f"- {aid} (tools: {', '.join(sorted(tools))})" if tools else f"- {aid}")
    return "\n".join(lines)


def _resolve_step_field(span: dict, prop: str) -> str | None:
    """One property of a step span. Soft-miss (None) when the field doesn't apply to this span."""
    if prop == "tool_call":
        tcs = span.get("tool_calls")
        if tcs:
            return _clip(json.dumps(tcs, ensure_ascii=False, indent=2), _STEP_CLIP)
        names = [str(n) for n in (span.get("tool_call_names") or []) if n]
        if names:
            return ", ".join(names)
        if span.get("type") == TOOL:
            return _clip(content_text(span.get("input")), _STEP_CLIP) or None
        return None
    if prop == "tool_result":
        if span.get("type") == TOOL:
            return _clip(content_text(span.get("output")), _STEP_CLIP) or None
        return None
    if prop == "thinking":
        if span.get("type") == THINKING:
            txt = content_text(span.get("output")) or content_text(span.get("input"))
            return _clip(txt, _STEP_CLIP) or None
        return None
    if prop == "output_content":
        return _clip(content_text(span.get("output")), _STEP_CLIP) or None
    if prop == "output_structured":
        return _structured(span.get("output"))
    return None  # unknown property → soft miss


def _structured(out: Any) -> str | None:
    """The step output as pretty JSON when it's structured; soft-miss otherwise."""
    if isinstance(out, (dict, list)):
        return _clip(json.dumps(out, ensure_ascii=False, indent=2), _STRUCT_CLIP)
    if isinstance(out, str):
        s = out.strip()
        if s[:1] in ("[", "{"):
            try:
                return _clip(json.dumps(json.loads(s), ensure_ascii=False, indent=2), _STRUCT_CLIP)
            except ValueError:
                return None
    return None


def _format_step(span: dict) -> str | None:
    """Human-readable multi-line dump of a step (bare `@CURRENT_STEP` / `@PREVIOUS_STEP`)."""
    lines = [f"Step type: {span.get('type', '') or 'STEP'}"]
    if span.get("name"):
        lines.append(f"Name: {span['name']}")
    for label, prop in (("Tool call", "tool_call"), ("Tool result", "tool_result"),
                        ("Thinking", "thinking"), ("Output", "output_content")):
        val = _resolve_step_field(span, prop)
        if val:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


def _format_steps(spans: list[dict]) -> str | None:
    if not spans:
        return None
    blocks = []
    for i, s in enumerate(spans, start=1):
        body = _format_step(s) or ""
        blocks.append(f"Step {i}:\n{body}")
    return "\n\n".join(blocks)


def _resolve_message_field(msg: dict, prop: str) -> str | None:
    if prop == "role":
        return msg.get("role") or "assistant"
    val = msg.get(prop)
    return _clip(val, _MSG_CLIP) if val else None


def _format_message(msg: dict) -> str | None:
    parts = []
    if msg.get("input"):
        parts.append(f"User: {_clip(msg['input'], _MSG_CLIP)}")
    if msg.get("output"):
        parts.append(f"Assistant: {_clip(msg['output'], _MSG_CLIP)}")
    return "\n".join(parts) or None


# ── context builder (pure) ───────────────────────────────────────────────────


_STRING_ATTRS = {
    "HISTORY": "history", "GOAL": "goal", "LIST_AGENT": "agents", "MESSAGES": "messages",
    "USER_MESSAGES": "user_messages", "ASSISTANT_MESSAGES": "assistant_messages",
    "FIRST_USER_MSG": "first_user_msg", "LAST_USER_MSG": "last_user_msg",
    "LAST_ASSISTANT_MSG": "last_assistant_msg", "PREVIOUS_USER_MSG": "previous_user_msg",
    "PREVIOUS_ASSISTANT_MSG": "previous_assistant_msg", "CURRENT_STEPS": "current_steps",
    "CURRENT_STEPS_COUNT": "current_steps_count", "STEP_NUMBER": "step_number",
}
_OBJECT_ATTRS = {"CURRENT_MESSAGE": "current_message", "CURRENT_STEP": "current_step", "PREVIOUS_STEP": "previous_step"}

# Vars that need the WHOLE thread (used to gate the extra thread-spans read in the service).
CONVERSATION_SCOPED_VARS = frozenset({
    "HISTORY", "MESSAGES", "USER_MESSAGES", "ASSISTANT_MESSAGES", "FIRST_USER_MSG",
    "LAST_USER_MSG", "LAST_ASSISTANT_MSG", "GOAL", "LIST_AGENT",
    "PREVIOUS_USER_MSG", "PREVIOUS_ASSISTANT_MSG",
})


def references_conversation_scope(refs: list[str] | None) -> bool:
    """True when any ref needs cross-trace data — the service uses this to decide whether to
    fetch the full thread for an advanced trace/step eval."""
    names = _base_names(refs)
    return bool(names and names & CONVERSATION_SCOPED_VARS)


def build_context(
    level: str,
    *,
    thread_spans: list[dict],
    current_trace_id: str = "",
    current_span_id: str | None = None,
    metric_previous_result: dict | None = None,
    wanted_vars: list[str] | None = None,
) -> EvaluationContext:
    """Build the `EvaluationContext` for ONE evaluated item from already-fetched span dicts.

    `thread_spans` is the full conversation when conversation-scoped vars are referenced, else
    just the current trace's spans (the conversation collapses to one turn — fine, since the
    cross-trace vars aren't materialized). `wanted_vars` (bare names) restricts materialization to
    referenced variables; `None` materializes everything applicable.
    """
    ctx = EvaluationContext(metric_previous_result=metric_previous_result)
    want = _base_names(wanted_vars)

    def need(name: str) -> bool:
        return want is None or name in want

    turns = _group_turns(thread_spans)
    if not turns:
        return ctx
    ios = [(_turn_io(spans)) for _, spans in turns]  # [(user, answer), ...]
    cl = catalog_level(level)

    # whole-conversation vars
    if need("HISTORY") or need("MESSAGES"):
        lines: list[str] = []
        for user, answer in ios:
            if user:
                lines.append(f"[user]: {_clip(user, _MSG_CLIP)}")
            if answer:
                lines.append(f"[assistant]: {_clip(answer, _MSG_CLIP)}")
        transcript = _clip("\n".join(lines), _HISTORY_CLIP)
        ctx.history = transcript or None
        ctx.messages = transcript or None
    if need("USER_MESSAGES"):
        ctx.user_messages = "\n".join(f"[user]: {_clip(u, _MSG_CLIP)}" for u, _ in ios if u) or None
    if need("ASSISTANT_MESSAGES"):
        ctx.assistant_messages = "\n".join(f"[assistant]: {_clip(a, _MSG_CLIP)}" for _, a in ios if a) or None
    users = [u for u, _ in ios if u]
    answers = [a for _, a in ios if a]
    if need("FIRST_USER_MSG") or need("GOAL"):
        first_user = _clip(users[0], _MSG_CLIP) if users else None
        ctx.first_user_msg = first_user
        ctx.goal = first_user  # best-effort: the initial request is the user's goal/intent
    if need("LAST_USER_MSG"):
        ctx.last_user_msg = _clip(users[-1], _MSG_CLIP) if users else None
    if need("LAST_ASSISTANT_MSG"):
        ctx.last_assistant_msg = _clip(answers[-1], _MSG_CLIP) if answers else None
    if need("LIST_AGENT"):
        ctx.agents = _format_agents(thread_spans)

    if cl == CL_CONVERSATION:
        return ctx

    # message / step: locate the current turn (by trace_id; fall back to the last turn)
    cur_idx = next((i for i, (tid, _) in enumerate(turns) if tid == current_trace_id), len(turns) - 1)
    cur_spans = turns[cur_idx][1]
    cur_user, cur_answer = ios[cur_idx]
    # "steps" = the turn's spans minus the agent-root wrapper (so the first real step is step 1),
    # falling back to all spans for a single-span (root-is-the-step) trace.
    cur_root = root_span(cur_spans)
    step_spans = [s for s in cur_spans if s.get("span_id") != cur_root.get("span_id")] or cur_spans
    if need("CURRENT_MESSAGE"):
        ctx.current_message = {"input": cur_user, "output": cur_answer, "role": "assistant"}
    if need("CURRENT_STEPS"):
        ctx.current_steps = _format_steps(step_spans)
    if need("CURRENT_STEPS_COUNT"):
        ctx.current_steps_count = str(len(step_spans))
    if cur_idx > 0:
        prev_user, prev_answer = ios[cur_idx - 1]
        if need("PREVIOUS_USER_MSG"):
            ctx.previous_user_msg = _clip(prev_user, _MSG_CLIP) if prev_user else None
        if need("PREVIOUS_ASSISTANT_MSG"):
            ctx.previous_assistant_msg = _clip(prev_answer, _MSG_CLIP) if prev_answer else None

    if cl != CL_STEP:
        return ctx

    # step: locate the current step within the turn (by span_id; fall back to the first step)
    step_idx = next(
        (i for i, s in enumerate(step_spans) if s.get("span_id") == current_span_id), 0
    )
    if step_spans:
        if need("CURRENT_STEP"):
            ctx.current_step = step_spans[step_idx]
        if need("STEP_NUMBER"):
            ctx.step_number = str(step_idx + 1)
        if need("PREVIOUS_STEP") and step_idx > 0:
            ctx.previous_step = step_spans[step_idx - 1]
    return ctx


# ── resolver ─────────────────────────────────────────────────────────────────


def _resolve_variable(name: str, prop: str | None, ctx: EvaluationContext) -> str | None:
    if name == "METRIC_PREVIOUS_RESULT":
        r = ctx.metric_previous_result
        return json.dumps(r, ensure_ascii=False, indent=2) if r else None
    if name in _STRING_ATTRS:
        return getattr(ctx, _STRING_ATTRS[name])
    if name in _OBJECT_ATTRS:
        obj = getattr(ctx, _OBJECT_ATTRS[name])
        if not obj:
            return None
        if name == "CURRENT_MESSAGE":
            return _resolve_message_field(obj, prop) if prop else _format_message(obj)
        return _resolve_step_field(obj, prop) if prop else _format_step(obj)
    return None  # unknown variable → soft miss


class TemplateResolver:
    """Substitutes `@VARIABLE` / `@VARIABLE.prop` against an `EvaluationContext`. Missing values
    become `[No <REF> available]`; never raises (a formatter blowup degrades to a soft miss)."""

    def resolve(self, template: str, context: EvaluationContext) -> ResolvedTemplate:
        used: list[str] = []
        missing: list[str] = []

        def repl(m: re.Match) -> str:
            name, prop = m.group(1), m.group(2)
            ref = name + (f".{prop}" if prop else "")
            try:
                val = _resolve_variable(name, prop, context)
            except Exception:
                val = None
            if not val:
                if ref not in missing:
                    missing.append(ref)
                return f"[No {ref} available]"
            if ref not in used:
                used.append(ref)
            return val

        text = VARIABLE_RE.sub(repl, template or "")
        return ResolvedTemplate(text, used, missing)


template_resolver = TemplateResolver()
