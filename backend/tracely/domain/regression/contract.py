"""Fail-to-pass contract evaluation: take a regression case's assertions and a produced
trajectory, return PASS/FAIL with the diagnostic detail dict the UI/CLI surfaces.

Pure: no I/O, no settings, no DB. The match modes come from `agentevals` and live in
`domain/trajectory.py`.
"""

from __future__ import annotations

from typing import Any

from tracely.domain.trajectory import (
    Trajectory,
    erroring_steps,
    split_errors,
    tool_sequence,
    tools_satisfied,
)


def evaluate_case(case, traj: Trajectory) -> tuple[str, dict]:
    """Convenience: pull `assertions` + `match_mode` off an `EvaluationCase` and evaluate.

    Type-loose on `case` so callers don't have to drag in the SQLAlchemy model — anything with
    `.assertions` and `.match_mode` attributes works.
    """
    return evaluate_assertions(case.assertions or {}, case.match_mode, traj)


def apply_quality(
    verdict: str,
    detail: dict[str, Any],
    quality: list[dict] | None,
    *,
    blocks: bool,
) -> tuple[str, dict]:
    """Fold answer-quality judge results into a structural case verdict (the judge-in-the-gate).

    `quality` is what re-running the case's answer-quality judge(s) on the produced trajectory's
    trace yielded — a list of `{score_name, verdict, value, comment}`. A FAIL flips the case to
    FAIL when `blocks` (the default), catching wrong/hallucinated answers a structural check
    (tool sequence + no-error) cannot. When not blocking, the result is recorded but advisory.

    Pure: the (impure) judge call happens in the service; this only combines the outcome. When
    `quality` is empty/None — no quality assertion, no enabled judge, or no LLM key — the verdict
    is unchanged and `quality_checked=False` records that the answer wasn't graded.
    """
    if not quality:
        return verdict, {**detail, "quality_checked": False}
    failed = [q for q in quality if q.get("verdict") == "FAIL"]
    worst = failed[0] if failed else quality[0]
    merged = {
        **detail,
        "quality_checked": True,
        "quality_pass": not failed,
        "quality_score": worst.get("value"),
        "quality_score_name": worst.get("score_name"),
        "quality_reason": worst.get("comment"),
    }
    if failed and blocks:
        return "FAIL", merged
    return verdict, merged


def evaluate_assertions(
    assertions: dict[str, Any],
    match_mode_default: str,
    traj: Trajectory,
) -> tuple[str, dict]:
    """Run a case's assertions against a produced trajectory.

    `assertions` is the JSON blob from `EvaluationCase.assertions`. `match_mode_default` is the
    case's `match_mode` column, used as a fallback when assertions don't override it (so the
    legacy assertion shape `{required_tools, no_error}` keeps working).
    """
    ref_tools: list[str] = assertions.get("required_tools", [])
    mode: str = assertions.get("match_mode", match_mode_default or "superset")
    produced = tool_sequence(traj)
    tools_ok, missing, extra = tools_satisfied(mode, produced, ref_tools)
    no_error_required = assertions.get("no_error", True)
    # allow_tool_errors: a tool may fail (it's the replayed environment) as long as the agent's
    # own run handles it — so an error-HANDLING fix can pass even though the tool fixture errors.
    allow_tool_errors = assertions.get("allow_tool_errors", False)
    errs = erroring_steps(traj)
    tool_errs, run_errs = split_errors(traj)
    if not no_error_required:
        error_ok = True
    elif allow_tool_errors:
        error_ok = len(run_errs) == 0  # tools may error; the run outcome must be clean
    else:
        error_ok = len(errs) == 0
    passed = tools_ok and error_ok
    detail = {
        "passed": passed,
        "tools_ok": tools_ok,
        "error_ok": error_ok,
        "match_mode": mode,
        "allow_tool_errors": allow_tool_errors,
        "required_tools": ref_tools,
        "produced_tools": produced,
        "missing_tools": missing,
        "extra_tools": extra,
        "erroring_steps": errs,
        "tool_errors": tool_errs,
        "run_errors": run_errs,
    }
    return ("PASS" if passed else "FAIL"), detail
