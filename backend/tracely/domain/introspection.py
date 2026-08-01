"""Recording what Tracely itself did, as a trace.

When an evaluator grades a run or a scenario drives a conversation, the interesting part —
*which prompt went to which model, and what came back* — used to exist only in worker logs. This
module captures it into an ordinary OTLP payload, so the trace viewer that already renders agent
runs renders Tracely's own runs too.

Two kinds, kept apart by `internal_kind`:

- `eval` — one recording per evaluation of a trace, a group span per evaluator.
- `sim`  — one recording per scenario phase (driving, then grading).

Pure: dataclasses plus payload building. `services/introspection_service.py` owns the contextvar
lifecycle and the emit; `infrastructure/llm/provider.py` appends a step per LLM call.

**Recordings are never evaluated.** `internal_kind` is non-empty on every span here, and both the
ingest hop and `EvaluationService` refuse to grade such a trace — otherwise grading an eval run
would record another eval run, without end.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import dataclass, field

from tracely.domain import otlp_payload as otlp

EVAL = "eval"
SIM = "sim"

# The recording in progress on this task, if any. Lives here rather than in the service so
# `infrastructure/llm/provider.py` can append to it without importing upwards through the layers.
_active: contextvars.ContextVar["Recording | None"] = contextvars.ContextVar(
    "tracely_recording", default=None
)


def active() -> "Recording | None":
    return _active.get()

# Observation types, chosen so the existing renderers do the right thing: GENERATION shows the
# model + token counts, TOOL shows a call, CHAIN groups.
_GENERATION = "GENERATION"
_CHAIN = "CHAIN"


@dataclass
class Step:
    """One thing that happened: an LLM call, an HTTP request to the customer's endpoint, a
    decision. `group` is the label it belongs under (an evaluator name, a turn) — steps with the
    same group share a parent span."""

    name: str
    input: str = ""
    output: str = ""
    group: str = ""
    obs_type: str = _GENERATION
    model: str = ""
    tokens: dict[str, int] = field(default_factory=dict)
    error: str = ""
    start_ns: int = 0
    end_ns: int = 0


@dataclass
class Group:
    """One unit of work inside a recording — an evaluator, a conversation turn. Carries its own
    input/output so it is legible on its own: reading `llm_judge · AGENT_RUN` → `FAIL — invented a
    refund policy` should not require expanding it."""

    name: str
    input: str = ""
    output: str = ""
    error: str = ""


@dataclass
class Recording:
    """An in-progress recording. `label` is the group new steps are filed under — callers set it
    as they move through their work (per evaluator, per turn) so a flat sequence of provider calls
    becomes a readable tree.

    Setting `label` *declares* the group, so a unit of work that makes no LLM call at all (a
    structural evaluator) still appears. Otherwise the recording would silently show only the
    evaluators that happened to call a model, which reads as "these are the ones that ran".
    """

    kind: str
    subject_id: str
    name: str
    project_id: str = ""
    agent_slug: str = ""
    env: str = "prod"
    # What the run is ABOUT, in words. The subject id alone is unreadable as a title.
    subject_label: str = ""
    steps: list[Step] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    start_ns: int = field(default_factory=time.time_ns)
    _label: str = ""

    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, name: str) -> None:
        self._label = name
        if name and not any(g.name == name for g in self.groups):
            self.groups.append(Group(name))

    def describe(self, *, input: str = "", output: str = "", error: str = "") -> None:
        """Set the current group's own input/output — what it was asked to do and what it decided.
        This is what replaced a separate 'verdict' child span per evaluator: one row, not two."""
        group = next((g for g in self.groups if g.name == self._label), None)
        if group is None:
            return
        if input:
            group.input = input
        if output:
            group.output = output
        if error:
            group.error = error

    def add(
        self,
        name: str,
        *,
        input: str = "",
        output: str = "",
        obs_type: str = _GENERATION,
        model: str = "",
        tokens: dict[str, int] | None = None,
        error: str = "",
        start_ns: int = 0,
    ) -> None:
        now = time.time_ns()
        self.steps.append(Step(
            name=name, input=input, output=output, group=self.label, obs_type=obs_type,
            model=model, tokens=tokens or {}, error=error,
            start_ns=start_ns or now, end_ns=now,
        ))


def _usage(tokens: dict[str, int]) -> list[dict]:
    """Token counts as the `gen_ai.usage.*` attributes the span mapper already reads."""
    out = []
    for key, attr_name in (
        ("input_tokens", "gen_ai.usage.input_tokens"),
        ("output_tokens", "gen_ai.usage.output_tokens"),
        ("total_tokens", "gen_ai.usage.total_tokens"),
    ):
        if tokens.get(key):
            out.append(otlp.attr(attr_name, int(tokens[key])))
    return out


def payload(rec: Recording) -> dict | None:
    """The whole recording as an ExportTraceServiceRequest, or None when nothing was recorded.

    Shape: a root span, one CHAIN per group, and each step underneath its group. Every span
    carries `tracely.internal.kind`, which is what keeps these traces out of the lists and out of
    the evaluator's reach.
    """
    if not rec.steps and not rec.groups:
        return None

    trace_id = uuid.uuid4().bytes
    end_ns = max((s.end_ns for s in rec.steps), default=time.time_ns())

    def base(extra: list[dict] | None = None) -> list[dict]:
        return [
            otlp.attr("tracely.internal.kind", rec.kind),
            otlp.attr("tracely.internal.subject_id", rec.subject_id),
            otlp.attr("tracely.env", rec.env),
            *([otlp.attr("tracely.agent.id", rec.agent_slug)] if rec.agent_slug else []),
            *(extra or []),
        ]

    root_id = uuid.uuid4().bytes[:8]
    spans = [otlp.span(
        trace_id=trace_id, span_id=root_id, name=rec.name,
        start_ns=rec.start_ns, end_ns=end_ns,
        attributes=base([
            otlp.attr("tracely.observation.type", _CHAIN),
            otlp.attr("tracely.is_app_root", True),
            otlp.attr("tracely.trace.name", rec.name),
            otlp.attr("tracely.input", rec.subject_label or rec.subject_id),
            otlp.attr(
                "tracely.output",
                " · ".join(f"{g.name}: {g.output}" for g in rec.groups if g.output)
                or f"{len(rec.steps)} step(s)",
            ),
        ]),
    )]

    # One span per DECLARED group, in declaration order — including groups that recorded no step,
    # so a structural evaluator is visible as having run rather than silently absent.
    group_ids: dict[str, bytes] = {}
    for group in rec.groups:
        members = [s for s in rec.steps if s.group == group.name]
        gid = uuid.uuid4().bytes[:8]
        group_ids[group.name] = gid
        spans.append(otlp.span(
            trace_id=trace_id, span_id=gid, parent_span_id=root_id, name=group.name,
            start_ns=members[0].start_ns if members else rec.start_ns,
            end_ns=max((m.end_ns for m in members), default=rec.start_ns),
            attributes=base([
                otlp.attr("tracely.observation.type", _CHAIN),
                otlp.attr("tracely.step.name", group.name),
                otlp.attr("tracely.input", group.input),
                otlp.attr("tracely.output", group.output),
            ]),
            error=group.error or "; ".join(m.error for m in members if m.error),
        ))

    for step in rec.steps:
        spans.append(otlp.span(
            trace_id=trace_id, span_id=uuid.uuid4().bytes[:8],
            parent_span_id=group_ids.get(step.group, root_id),
            name=step.name, start_ns=step.start_ns, end_ns=step.end_ns,
            attributes=base([
                otlp.attr("tracely.observation.type", step.obs_type),
                otlp.attr("tracely.input", step.input),
                otlp.attr("tracely.output", step.output),
                *([otlp.attr("tracely.model", step.model)] if step.model else []),
                *_usage(step.tokens),
            ]),
            error=step.error,
        ))
    return otlp.request(spans, scope_name=f"tracely.internal.{rec.kind}")
