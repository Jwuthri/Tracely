"""Example agent entrypoint for `tracely replay`.

`tracely replay --entrypoint weather_agent:run` calls one of these with each promoted case's
recorded input, inside an env=ci agent span the CLI opens for you — so the function just emits
its child llm/tool spans (via call_llm / call_tool) and returns the answer.

These use `tracely.call_llm` / `tracely.call_tool`, which in HERMETIC replay serve the recorded
output and never invoke the live function. We make the live model RAISE on purpose: if replay is
hermetic, it's never called; with `--live` it blows up — proving CI isn't hitting the real model.

    tracely replay planner --entrypoint weather_agent:run          # fixed   -> gate PASS
    tracely replay planner --entrypoint weather_agent:run_broken   # regressed-> gate FAIL
    tracely replay planner --entrypoint weather_agent:run --live    # -> live model raises
"""

from __future__ import annotations

import tracely_sdk as tracely


def _live_model(prompt: str) -> str:
    raise RuntimeError("LIVE model call — would cost money / be nondeterministic in CI")


def run(prompt: str) -> str:
    """Fixed agent: consults the model (served from the recorded fixture in hermetic replay — the
    live model is never called), then actually calls get_weather (the fix the silent case wanted)."""
    answer = tracely.call_llm("gpt-4o", lambda: _live_model(prompt), input=prompt)
    tracely.call_tool("get_weather", lambda: '{"tempF": 64}')
    return answer


def run_broken(prompt: str) -> str:
    """Regression: answers straight from the model WITHOUT calling get_weather — the silent
    failure the promoted case was built to catch. The gate FAILs (required tool missing)."""
    return tracely.call_llm("gpt-4o", lambda: _live_model(prompt), input=prompt)
