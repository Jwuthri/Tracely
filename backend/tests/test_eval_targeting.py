"""Evaluator targeting + sampling (the on-ingest run knobs) — pure, no infra.

These are the previously-dead `Evaluator.target_agent / target_env / sampling` fields, now
actually read by the runner. Sampling must be DETERMINISTIC per (trace, evaluator) so a
re-ingested trace re-evaluates to the same keep/drop decision.
"""

from __future__ import annotations

from tracely.domain.evaluation.targeting import spec_applies


def _spec(**kw) -> dict:
    return {"score_name": "tracely.run.quality", "target_agent": "", "target_env": "", "sampling": 1.0, **kw}


def _applies(spec, **ctx) -> bool:
    base = {"agent_id": "a-id", "agent_slug": "planner", "env": "prod", "trace_id": "t1"}
    return spec_applies(spec, **{**base, **ctx})


# ── targeting ────────────────────────────────────────────────────────────────
def test_no_targets_applies_to_everything():
    assert _applies(_spec()) is True


def test_target_env_filters():
    assert _applies(_spec(target_env="prod")) is True
    assert _applies(_spec(target_env="ci")) is False


def test_target_agent_matches_slug_or_id():
    assert _applies(_spec(target_agent="planner")) is True   # by slug
    assert _applies(_spec(target_agent="a-id")) is True       # by id
    assert _applies(_spec(target_agent="other")) is False


# ── sampling (deterministic) ─────────────────────────────────────────────────
def test_sampling_one_always_runs():
    assert _applies(_spec(sampling=1.0)) is True


def test_sampling_zero_never_runs():
    assert _applies(_spec(sampling=0.0)) is False


def test_sampling_is_deterministic_per_trace_and_metric():
    spec = _spec(sampling=0.5)
    first = _applies(spec, trace_id="trace-xyz")
    # same (trace, metric) → identical decision every time (idempotent re-ingest)
    assert all(_applies(spec, trace_id="trace-xyz") == first for _ in range(20))


def test_sampling_half_keeps_roughly_half_across_traces():
    spec = _spec(sampling=0.5)
    kept = sum(_applies(spec, trace_id=f"trace-{i}") for i in range(2000))
    assert 850 < kept < 1150  # ~1000 of 2000, generous bounds for hash spread


def test_sampling_decision_varies_by_metric_name():
    # two metrics on the same trace get independent dice (not all-or-nothing)
    a = _applies(_spec(score_name="m.a", sampling=0.5), trace_id="t-fixed")
    b = _applies(_spec(score_name="m.b", sampling=0.5), trace_id="t-fixed")
    # not a strict assertion that they differ, but the buckets must be computed independently
    from tracely.domain.evaluation.targeting import _sample_bucket
    assert _sample_bucket("t-fixed", "m.a") != _sample_bucket("t-fixed", "m.b")
    _ = (a, b)
