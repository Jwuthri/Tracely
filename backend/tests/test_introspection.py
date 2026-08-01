"""Recording Tracely's own work as a trace (`domain/introspection.py`).

The load-bearing property here is NOT the pretty tree — it is that a recording can never be
evaluated. An eval run that gets evaluated records another eval run, which gets evaluated: the
worker fills with work that generates more work, and the first symptom is a bill.
"""

from __future__ import annotations

import base64

import pytest

from tracely.domain import introspection
from tracely.domain.introspection import Recording


def _spans(payload):
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"]


def _attrs(span):
    out = {}
    for a in span["attributes"]:
        v = a["value"]
        out[a["key"]] = v.get("stringValue", v.get("boolValue", v.get("intValue")))
    return out


def _rec(**over):
    kw = dict(kind=introspection.EVAL, subject_id="tr1", name="eval · 2", project_id="p1")
    kw.update(over)
    return Recording(**kw)


# ── the loop guard ────────────────────────────────────────────────────────────


def test_every_span_is_marked_internal():
    """The mark is the guard: ingest and EvaluationService both refuse a trace that has it, so a
    span that slips through unmarked is a span that gets evaluated — and evaluating an evaluation
    never terminates."""
    rec = _rec()
    rec.label = "correctness"
    rec.add("openai/gpt-5", input="grade this", output="PASS")

    spans = _spans(introspection.payload(rec))

    assert spans, "a recording with steps must produce spans"
    for span in spans:
        assert _attrs(span)["tracely.internal.kind"] == "eval"


def test_nothing_recorded_means_no_trace():
    """Nothing declared and nothing done — emitting an empty trace for that would bury the real
    recordings."""
    assert introspection.payload(_rec()) is None


# ── legibility ────────────────────────────────────────────────────────────────


def test_a_group_that_made_no_llm_call_still_appears():
    """A structural evaluator calls no model. If only groups with steps were emitted, the
    recording would show the judges alone and read as 'these are the ones that ran'."""
    rec = _rec()
    rec.label = "tracely.run.outcome"
    rec.describe(input="structural · AGENT_RUN", output="PASS")

    names = [s["name"] for s in _spans(introspection.payload(rec))]
    assert "tracely.run.outcome" in names


def test_the_verdict_lives_on_the_evaluator_span():
    """One row per evaluator, not two. A separate child 'verdict' event doubled the row count and
    told the reader nothing its parent couldn't."""
    rec = _rec()
    rec.label = "tracely.run.quality"
    rec.describe(input="llm_judge · AGENT_RUN · basic", output="FAIL — invented a refund policy")

    spans = _spans(introspection.payload(rec))
    assert not any(s["name"] == "verdict" for s in spans)
    a = _attrs(next(s for s in spans if s["name"] == "tracely.run.quality"))
    assert a["tracely.input"] == "llm_judge · AGENT_RUN · basic"
    assert "invented a refund policy" in a["tracely.output"]


def test_the_root_says_what_was_graded_not_just_its_id():
    """The id alone as a title was the complaint: `0000…1f1ffee` tells a reader nothing."""
    rec = _rec(subject_label="grading trace tr1\n\nWhere is my order?")
    rec.label = "x"
    rec.describe(output="PASS")

    root = next(s for s in _spans(introspection.payload(rec)) if "parentSpanId" not in s)
    assert "Where is my order?" in _attrs(root)["tracely.input"]


def test_the_root_summarises_every_verdict():
    """So a collapsed recording still answers "what did this eval decide?"."""
    rec = _rec()
    rec.label = "a"
    rec.describe(output="PASS")
    rec.label = "b"
    rec.describe(output="FAIL — rude")

    root = next(s for s in _spans(introspection.payload(rec)) if "parentSpanId" not in s)
    out = _attrs(root)["tracely.output"]
    assert "a: PASS" in out and "b: FAIL — rude" in out


def test_groups_keep_declaration_order():
    """Evaluators run in dependency order; the recording must not reshuffle them."""
    rec = _rec()
    for name in ("first", "second", "third"):
        rec.label = name
        rec.describe(output="PASS")

    spans = _spans(introspection.payload(rec))
    root = next(s for s in spans if "parentSpanId" not in s)
    groups = [s["name"] for s in spans if s.get("parentSpanId") == root["spanId"]]
    assert groups == ["first", "second", "third"]


# ── shape ─────────────────────────────────────────────────────────────────────


def test_ids_are_base64_so_the_otlp_parser_can_read_them():
    """Same trap as emulated turns: protobuf's json_format decodes `bytes` as base64, and hex does
    not raise — it silently yields a 24-byte id nothing can look up."""
    rec = _rec()
    rec.add("call", input="x", output="y")

    for span in _spans(introspection.payload(rec)):
        assert len(base64.b64decode(span["traceId"], validate=True)) == 16
        assert len(base64.b64decode(span["spanId"], validate=True)) == 8


def test_steps_nest_under_their_group():
    """Grouping is what makes the recording readable: 'which evaluator asked this?' has to be
    answerable by looking at the tree, not by reading prompts."""
    rec = _rec()
    rec.label = "correctness"
    rec.add("openai/gpt-5", input="a", output="b")
    rec.label = "tone"
    rec.add("openai/gpt-5", input="c", output="d")

    spans = _spans(introspection.payload(rec))
    by_id = {s["spanId"]: s for s in spans}
    root = next(s for s in spans if "parentSpanId" not in s)
    groups = {s["name"]: s for s in spans if s.get("parentSpanId") == root["spanId"]}

    assert set(groups) == {"correctness", "tone"}
    leaves = [s for s in spans if s.get("parentSpanId") in {g["spanId"] for g in groups.values()}]
    assert len(leaves) == 2
    assert by_id[leaves[0]["parentSpanId"]]["name"] == "correctness"


def test_ungrouped_steps_hang_off_the_root():
    rec = _rec()
    rec.add("solo", input="a", output="b")

    spans = _spans(introspection.payload(rec))
    root = next(s for s in spans if "parentSpanId" not in s)
    assert [s["name"] for s in spans if s.get("parentSpanId") == root["spanId"]] == ["solo"]


def test_the_prompt_and_the_reply_are_both_kept():
    """The whole point: 'why did the judge say that' is answered by reading what it was asked."""
    rec = _rec()
    rec.add("openai/gpt-5", input="[system]\nbe strict\n\n[user]\ngrade", output="FAIL: rude")

    leaf = next(s for s in _spans(introspection.payload(rec)) if s["name"] == "openai/gpt-5")
    a = _attrs(leaf)
    assert "be strict" in a["tracely.input"] and a["tracely.output"] == "FAIL: rude"


def test_a_failed_step_carries_the_error():
    rec = _rec()
    rec.label = "correctness"
    rec.add("openai/gpt-5", input="a", error="rate limited")

    spans = _spans(introspection.payload(rec))
    leaf = next(s for s in spans if s["name"] == "openai/gpt-5")
    group = next(s for s in spans if s["name"] == "correctness")
    assert leaf["status"]["code"] == 2 and "rate limited" in leaf["status"]["message"]
    # The group surfaces it too, so a collapsed tree still shows something went wrong.
    assert group["status"]["code"] == 2


def test_subject_travels_on_every_span():
    """`subject_id` is how the UI finds 'the eval for THIS trace'; a span without it is orphaned."""
    rec = _rec(subject_id="conv-9", kind=introspection.SIM)
    rec.add("POST /chat", input="hi", output="hello")

    for span in _spans(introspection.payload(rec)):
        assert _attrs(span)["tracely.internal.subject_id"] == "conv-9"


def test_token_usage_is_reported_as_gen_ai_attributes():
    """So judge spend shows up in the recording with the same columns as any other LLM span."""
    rec = _rec()
    rec.add("openai/gpt-5", input="a", output="b",
            tokens={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128})

    leaf = next(s for s in _spans(introspection.payload(rec)) if s["name"] == "openai/gpt-5")
    assert _attrs(leaf)["gen_ai.usage.input_tokens"] == "120"


# ── the context manager ───────────────────────────────────────────────────────


def test_recording_is_off_when_disabled(monkeypatch):
    from tracely.services import introspection_service as svc

    monkeypatch.setattr(svc.settings, "introspection_enabled", False)
    with svc.record(introspection.EVAL, "tr1", "eval", project_id="p1") as rec:
        assert rec is None
        assert introspection.active() is None


def test_recordings_do_not_nest(monkeypatch):
    """Grading inside a scenario run must keep filing into the scenario's recording. Two open
    recordings would split one story across two traces with nothing linking them."""
    emitted: list = []
    from tracely.services import introspection_service as svc

    monkeypatch.setattr(svc, "_emit", emitted.append)
    with svc.record(introspection.SIM, "conv1", "outer", project_id="p1") as outer:
        with svc.record(introspection.EVAL, "tr1", "inner", project_id="p1") as inner:
            assert inner is None
            assert introspection.active() is outer

    assert [r.name for r in emitted] == ["outer"]


def test_the_active_recording_is_cleared_even_when_the_work_raises(monkeypatch):
    """A leaked contextvar would attach the next unrelated eval to this trace."""
    from tracely.services import introspection_service as svc

    monkeypatch.setattr(svc, "_emit", lambda _rec: None)
    with pytest.raises(ValueError):
        with svc.record(introspection.EVAL, "tr1", "eval", project_id="p1"):
            raise ValueError("boom")
    assert introspection.active() is None


def test_a_broken_emit_never_breaks_the_work(monkeypatch):
    """Recording is observability. A judge that graded correctly must not report failure because
    its recording could not be saved."""
    from tracely.services import introspection_service as svc

    monkeypatch.setattr(svc.blobstore, "put_blob", lambda *a, **k: (_ for _ in ()).throw(OSError("s3 down")))
    with svc.record(introspection.EVAL, "tr1", "eval", project_id="p1") as rec:
        rec.add("openai/gpt-5", input="a", output="b")
    # no exception escaped


# ── the loop guard, at both boundaries ────────────────────────────────────────


def test_ingest_never_schedules_evaluation_for_a_recording(monkeypatch):
    """Layer 1. Without this, ingesting an eval recording queues an evaluation of it, which
    records another recording — the worker generates its own work until someone notices the bill."""
    from tracely.workers import tasks

    scheduled: list[str] = []
    monkeypatch.setattr(
        tasks.IngestionService, "process_blob",
        lambda self, p, k, c: {
            "events": 4, "trace_ids": ["real-1", "rec-1"], "internal_trace_ids": ["rec-1"],
        },
    )
    monkeypatch.setattr(tasks.eval_debounce, "bump", lambda p, t: 1)
    monkeypatch.setattr(
        tasks.evaluate_run_task, "apply_async",
        lambda args, **kw: scheduled.append(args[1]),
    )

    tasks.ingest_otlp_blob.run("p1", "some/key.json", "application/json")

    assert scheduled == ["real-1"]


def test_evaluation_refuses_a_trace_that_is_itself_a_recording(monkeypatch):
    """Layer 2. Ingest is not the only caller — a monitor, a manual re-run or a backfill reaches
    `evaluate_trace` directly, and each is its own way into the same loop."""
    from tracely.services.evaluation_service import EvaluationService

    class _Reader:
        client = None

        def read_spans(self, project_id, trace_id):
            return [{"span_id": "s1", "parent_span_id": "", "internal_kind": "eval"}]

    svc = EvaluationService(trace_reader=_Reader(), score_writer=object())
    assert svc.evaluate_trace("p1", "rec-1") == {"scores": 0, "skipped": "internal"}
