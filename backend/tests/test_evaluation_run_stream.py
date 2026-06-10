"""The on-demand SSE run endpoint + the thread-level orchestration of EvaluationService."""

from __future__ import annotations

import json

from tracely.services.evaluation_service import EvaluationService


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _owner_token(client) -> str:
    r = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    return r.json()["token"]


_SPEC = {
    "id": "ev-1", "kind": "structural", "config": {"check": "run_outcome"},
    "score_name": "tracely.run.outcome", "level": "AGENT_RUN",
}


async def test_run_streams_per_score_frames(client, monkeypatch):
    tok = await _owner_token(client)

    monkeypatch.setattr(
        EvaluationService, "load_enabled_evaluators",
        staticmethod(lambda project_id, evaluator_ids=None: [_SPEC]),
    )

    def fake_thread(self, project_id, thread_id, specs=None, on_result=None):
        on_result({
            "name": "tracely.run.outcome", "evaluation_level": "AGENT_RUN",
            "observation_id": None, "value": 1.0, "string_value": "", "verdict": "PASS",
            "comment": "", "data_type": "BOOLEAN", "trace_id": "tr-1", "session_id": thread_id,
        })
        return {"scores": 1, "failures": 0}

    monkeypatch.setattr(EvaluationService, "evaluate_thread", fake_thread)

    frames: list[str] = []
    async with client.stream(
        "POST", "/api/evaluations/run", headers=_bearer(tok), json={"thread_ids": ["th-1"]}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                frames.append(line[len("data: "):])

    assert frames[-1] == "[DONE]"
    events = [json.loads(f) for f in frames[:-1]]
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "done"
    assert "result" in types and "target_done" in types
    result = next(e for e in events if e["type"] == "result")
    assert result["score"]["session_id"] == "th-1"
    assert result["score"]["verdict"] == "PASS"


async def test_run_trace_targets_skip_conversation(client, monkeypatch):
    tok = await _owner_token(client)
    monkeypatch.setattr(
        EvaluationService, "load_enabled_evaluators",
        staticmethod(lambda project_id, evaluator_ids=None: [_SPEC]),
    )
    seen: dict = {}

    def fake_trace(self, project_id, trace_id, specs=None, on_result=None, skip_conversation=False):
        seen["skip_conversation"] = skip_conversation
        seen["trace_id"] = trace_id
        return {"scores": 0, "failures": 0}

    monkeypatch.setattr(EvaluationService, "evaluate_trace", fake_trace)
    async with client.stream(
        "POST", "/api/evaluations/run", headers=_bearer(tok), json={"trace_ids": ["tr-9"]}
    ) as r:
        async for _ in r.aiter_lines():
            pass
    assert seen == {"skip_conversation": True, "trace_id": "tr-9"}


async def test_run_requires_targets(client):
    tok = await _owner_token(client)
    r = await client.post("/api/evaluations/run", headers=_bearer(tok), json={})
    assert r.status_code == 400


async def test_run_with_no_matching_evaluators_is_400(client, monkeypatch):
    tok = await _owner_token(client)
    monkeypatch.setattr(
        EvaluationService, "load_enabled_evaluators",
        staticmethod(lambda project_id, evaluator_ids=None: []),
    )
    r = await client.post(
        "/api/evaluations/run", headers=_bearer(tok), json={"thread_ids": ["th-1"]}
    )
    assert r.status_code == 400


# ── EvaluationService.evaluate_thread orchestration (no DB / no ClickHouse) ────────


class _FakeReader:
    def __init__(self, spans_by_trace: dict[str, list[dict]], order: list[str]) -> None:
        self.spans_by_trace, self.order = spans_by_trace, order

    def read_spans(self, project_id, trace_id):
        return self.spans_by_trace.get(trace_id, [])

    def read_thread_spans(self, project_id, thread_id):
        return [s for t in self.order for s in self.spans_by_trace[t]]

    def thread_trace_ids(self, project_id, thread_id):
        return list(self.order)


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list]] = []

    def write_eval_scores(self, project_id, trace_id, agent_run_id, results, thread_id=""):
        self.calls.append((trace_id, thread_id, list(results)))


def _ok_span(trace_id: str) -> dict:
    return {
        "span_id": f"{trace_id}-root", "parent_span_id": "", "type": "AGENT", "name": "run",
        "level": "DEFAULT", "status_message": "", "start_time": None, "end_time": None,
        "agent_id": "", "agent_run_id": trace_id, "input": "q", "output": "a",
        "tool_call_names": [], "trace_id": trace_id, "is_app_root": 1, "conversation_id": "th-1",
    }


def test_evaluate_thread_sequential_chains_across_turns():
    """A sequential metric's config gains __previous_result__ from the prior turn's result of
    the SAME metric; batch metrics never do; the first turn has no chain context."""
    from tracely.domain.evaluation.results import EvalResult

    class _FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def dispatch(self, kind, config, score_name, level, ctx):
            self.calls.append((score_name, dict(config)))
            n = sum(1 for name, _ in self.calls if name == score_name)
            return [EvalResult(score_name, "AGENT_RUN", "PASS", value=0.9, comment=f"turn {n}")]

    reader = _FakeReader({"t1": [_ok_span("t1")], "t2": [_ok_span("t2")]}, ["t1", "t2"])
    registry = _FakeRegistry()
    svc = EvaluationService(trace_reader=reader, score_writer=_FakeWriter(), registry=registry)  # type: ignore[arg-type]
    specs = [
        {"id": "seq", "kind": "llm_judge", "score_name": "custom.seq", "level": "AGENT_RUN",
         "config": {"prompt": "p", "execution_mode": "sequential"}},
        {"id": "batch", "kind": "llm_judge", "score_name": "custom.batch", "level": "AGENT_RUN",
         "config": {"prompt": "p"}},
    ]
    svc.evaluate_thread("p", "th-1", specs=specs)

    by_metric: dict[str, list[dict]] = {}
    for name, config in registry.calls:
        by_metric.setdefault(name, []).append(config)
    assert "__previous_result__" not in by_metric["custom.seq"][0]  # first turn: no context
    chained = by_metric["custom.seq"][1]["__previous_result__"]
    assert chained == {"value": 0.9, "verdict": "PASS", "reason": "turn 1"}
    assert all("__previous_result__" not in c for c in by_metric["custom.batch"])


def test_evaluate_thread_runs_turns_then_conversation():
    reader = _FakeReader({"t1": [_ok_span("t1")], "t2": [_ok_span("t2")]}, ["t1", "t2"])
    writer = _FakeWriter()
    svc = EvaluationService(trace_reader=reader, score_writer=writer)  # type: ignore[arg-type]
    specs = [
        {"id": "a", "kind": "structural", "config": {"check": "run_outcome"},
         "score_name": "tracely.run.outcome", "level": "AGENT_RUN"},
        {"id": "b", "kind": "structural", "config": {"check": "run_outcome"},
         "score_name": "custom.conv_outcome", "level": "CONVERSATION"},
    ]
    emitted: list[dict] = []
    out = svc.evaluate_thread("p", "th-1", specs=specs, on_result=emitted.append)

    assert out == {"scores": 3, "failures": 0}
    # two per-trace writes (thread stamped for session addressing) + one thread-scoped write
    assert [(c[0], c[1]) for c in writer.calls] == [("t1", "th-1"), ("t2", "th-1"), ("", "th-1")]
    conv_results = writer.calls[-1][2]
    assert [r.level for r in conv_results] == ["CONVERSATION"]
    conv_emit = next(e for e in emitted if e["evaluation_level"] == "CONVERSATION")
    assert conv_emit["trace_id"] is None and conv_emit["session_id"] == "th-1"
    run_emit = next(e for e in emitted if e["evaluation_level"] == "AGENT_RUN")
    assert run_emit["trace_id"] == "t1" and run_emit["session_id"] == "th-1"
