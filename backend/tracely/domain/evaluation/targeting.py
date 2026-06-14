"""Which evaluators apply to a given trace on the AUTO (on-ingest) run — targeting + sampling.

Pure: no I/O. The runner (`EvaluationService.evaluate_trace`) loads the project's enabled
evaluators, then drops the ones whose `target_agent` / `target_env` don't match the trace, and
rolls the per-evaluator `sampling` die. These three knobs are the only lever for controlling
LLM-judge spend ("grade 10% of prod traces with this judge") and scoping a judge to one
agent/env — previously stored on the `Evaluator` row but never read (the gate the review flagged).

Sampling is DETERMINISTIC per `(trace_id, score_name)`: a trace re-ingested across span batches
(which re-runs evaluation) makes the SAME keep/drop decision every time, so scores converge under
ReplacingMergeTree instead of flickering. Sampling/targeting govern only the automatic run — an
explicit on-demand run from the UI always grades, regardless.
"""

from __future__ import annotations

import hashlib


def _sample_bucket(trace_id: str, score_name: str) -> float:
    """A stable value in [0, 1) for a (trace, evaluator) pair — keep iff bucket < sampling."""
    h = hashlib.sha256(f"{trace_id}:{score_name}".encode()).hexdigest()
    return (int(h[:8], 16) % 10_000) / 10_000.0


def spec_applies(
    spec: dict,
    *,
    agent_id: str,
    agent_slug: str,
    env: str,
    trace_id: str,
) -> bool:
    """True if this evaluator should run on this trace under targeting + sampling.

    `target_agent` matches the trace's agent id OR slug (users set a slug; spans carry the id);
    `target_env` matches the trace's env; an empty target means "any". `sampling` (0..1) keeps the
    trace iff its deterministic bucket falls under the rate (1.0 = always, <=0 = never)."""
    target_agent = (spec.get("target_agent") or "").strip()
    if target_agent and target_agent not in {agent_id or "", agent_slug or ""}:
        return False
    target_env = (spec.get("target_env") or "").strip()
    if target_env and target_env != (env or ""):
        return False
    sampling = spec.get("sampling")
    if sampling is not None and sampling < 1.0:
        if sampling <= 0.0:
            return False
        if _sample_bucket(trace_id, spec.get("score_name", "")) >= sampling:
            return False
    return True
