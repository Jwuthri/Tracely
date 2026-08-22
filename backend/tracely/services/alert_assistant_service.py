"""Natural language → an alert flow draft.

"Slack me when the refund judge fails a live conversation, but only for the support bot" comes back
as a trigger plus a wired chain of steps the canvas can render immediately.

Deliberately ONE structured call rather than a tool-calling agent that mutates a draft: the draft
shape the canvas already produces is small enough to emit in full, and the model that has to
produce it is the same one that grades traces. It runs on the WORKSPACE's OpenRouter key
(`use_project_key` + `llm_enabled()` inside the wrap) because it is work on their data, exactly
like evaluator generation.

# ponytail: one shot, no streaming, no tool loop. Add tools when editing an existing 12-step flow
# starts losing step ids — the first symptom is a canvas that re-lays-out on every edit.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from tracely.domain.alerting import BASE_INPUTS, catalog_for_trigger, linear_flow_layout
from tracely.domain.monitoring.conditions import EVENT_TYPES, POLLED_TYPES
from tracely.infrastructure.llm import provider
from tracely.services.alert_flow_service import STEP_TYPES

log = structlog.get_logger()

TriggerLiteral = Literal[
    "gate_failed", "trace_failed", "cluster_new", "fail_rate_over", "score_below", "trace_failure_rate"
]
StepLiteral = Literal["condition", "webhook", "slack", "send_email", "llm_prompt", "python_expression"]


class GeneratedStep(BaseModel):
    name: str = Field(description="Short human name for the step, e.g. 'Post to Slack'")
    step_type: StepLiteral
    config: dict[str, Any] = Field(
        default_factory=dict, description="The step's config, shaped for its type"
    )


class GeneratedRule(BaseModel):
    name: str = Field(description="Short name for the alert")
    description: str = ""
    trigger: TriggerLiteral
    target_agent: str = Field(default="", description="Agent slug to scope to, or empty for all")
    contains: str = Field(default="", description="Substring filter on the failure text, or empty")
    score_name: str = Field(default="", description="Evaluator score name, or empty")
    env: str = Field(default="", description="Environment filter for gate alerts, or empty")
    threshold: float = Field(default=0.0, description="0..1 for threshold triggers, else 0")
    window_minutes: int = Field(default=60, description="Window for threshold triggers")
    min_samples: int = Field(default=20, description="Minimum samples for threshold triggers")
    steps: list[GeneratedStep] = Field(description="The flow, in run order")
    message: str = Field(
        description="One or two sentences for the user: what you drew, and what they must fill in"
    )


_STEP_SCHEMAS = """
condition          {"expression": "{{ jinja }}"}                  a gate; falsy stops the flow
slack              {"url": "", "text_template": "…"}              url MUST be left empty
send_email         {"to_template": "", "subject_template": "…", "body_template": "…"}
webhook            {"url": "", "method": "POST",
                    "headers": [{"key": "Authorization", "value": "Bearer "}],
                    "body_template": "{\\"k\\": \\"{{ v }}\\"}"}   url MUST be left empty
llm_prompt         {"model": "", "system_prompt": "…", "user_prompt_template": "…",
                    "temperature": 0, "output_schema": [{"name": "…", "type": "string",
                    "description": "…"}]}
python_expression  {"expression": "len(failing_evaluators)"}      no {{ }}, names directly
"""

_SYSTEM = """You design alert rules for Tracely, a trace-native CI/CD tool for AI agents.

An alert rule has two halves: a TRIGGER (when) and a FLOW of steps (what happens). Emit both.

TRIGGERS
  gate_failed         a CI gate run finished FAIL or NO_COVERAGE. Filters: env, contains.
  trace_failed        a live conversation turn failed a non-advisory evaluator.
                      Filters: score_name (one evaluator), contains (substring of the evaluator
                      names AND the judge's reason).
  cluster_new         a failure signature nothing had produced before. Filter: contains.
  fail_rate_over      one evaluator's FAIL rate over a window crossed `threshold` (0..1).
  score_below         one evaluator's average score fell under `threshold`.
  trace_failure_rate  the overall failing-trace rate crossed `threshold`.

STEP TYPES and their config shape:
{step_schemas}

TEMPLATES
Every string field is a Jinja template over these variables:
{catalog}
An upstream step's output is POSITIONAL: `{{{{ steps[0].result }}}}` is the first step upstream of
the one being configured, `steps[1]` the second. An llm_prompt step with a declared output_schema
exposes `steps[i].result.<field>`; without one, `steps[i].result.text`.

RULES
- NEVER invent a URL or an email address. Leave `url` / `to_template` empty — the user pastes
  their own, and say so in `message`.
- Prefer the fewest steps that do the job. Add a `condition` step only when the user asked to
  narrow it beyond what the trigger's own filters can express.
- Put an llm_prompt step in only when the user asks for written/classified output, and reference
  its result from the step after it.
- Use filters (score_name / contains / env / target_agent) rather than a condition step when the
  trigger supports them: they stop the flow from running at all, which is cheaper and clearer.
"""


def _catalog_lines(trigger: str) -> str:
    rows = catalog_for_trigger(trigger) if trigger else [
        {k: v for k, v in r.items() if k != "triggers"} for r in BASE_INPUTS
    ]
    return "\n".join(f"  {r['path']} ({r['type']}) — {r['description']}" for r in rows)


def generate_rule(
    project_id: str,
    prompt: str,
    *,
    trigger_hint: str = "",
    current: dict | None = None,
    agents: list[str] | None = None,
    score_names: list[str] | None = None,
) -> dict:
    """Draft (or redraft) a rule from a sentence. Raises `RuntimeError` when no LLM applies.

    `current` is the rule as the canvas has it right now. Inlining it is what makes "add a
    condition before the webhook" an edit rather than a rebuild from scratch — without it the model
    re-invents every step, and the canvas loses the ids that hold its layout together.
    """
    system = _SYSTEM.format(
        step_schemas=_STEP_SCHEMAS.strip(),
        catalog=_catalog_lines(trigger_hint),
    )
    parts = [f"Request: {prompt.strip()}"]
    if agents:
        parts.append(f"Agents in this workspace: {', '.join(agents[:20])}")
    if score_names:
        parts.append(f"Evaluator score names: {', '.join(score_names[:30])}")
    if current:
        parts.append(
            "The user is EDITING this rule. Keep what they did not ask you to change, including "
            f"step names:\n{current}"
        )
    with provider.use_project_key(project_id):
        if not provider.llm_enabled():
            raise RuntimeError("no OpenRouter key configured for this workspace")
        draft = provider.run_structured_agent(
            "\n\n".join(parts), response_format=GeneratedRule, system_prompt=system, temperature=0.1
        )

    steps = [
        {
            "id": f"s-gen-{i}",
            "order_index": i,
            "name": s.name or f"Step {i + 1}",
            "step_type": s.step_type,
            "config": s.config or {},
        }
        for i, s in enumerate(draft.steps)
        if s.step_type in STEP_TYPES
    ]
    condition: dict[str, Any] = {"type": draft.trigger}
    if draft.trigger in EVENT_TYPES:
        if draft.contains:
            condition["contains"] = draft.contains
        if draft.score_name and draft.trigger == "trace_failed":
            condition["score_name"] = draft.score_name
        if draft.env and draft.trigger == "gate_failed":
            condition["env"] = draft.env
    elif draft.trigger in POLLED_TYPES:
        condition["threshold"] = draft.threshold
        condition["window_minutes"] = max(draft.window_minutes, 1)
        condition["min_samples"] = max(draft.min_samples, 1)
        if draft.score_name:
            condition["score_name"] = draft.score_name

    log.info("alert_draft_generated", project_id=project_id, trigger=draft.trigger, steps=len(steps))
    return {
        "name": draft.name,
        "description": draft.description,
        "target_agent": draft.target_agent,
        "condition": condition,
        "steps": steps,
        # A linear chain: the canvas re-lays it out, and a generated graph the user cannot see
        # wired is worse than one they can drag apart.
        "flow_layout": linear_flow_layout(
            [(s["id"], s["name"], s["step_type"]) for s in steps], trigger_label=draft.trigger
        ),
        "message": draft.message,
    }
