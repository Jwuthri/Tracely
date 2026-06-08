"""`Evaluator` ABC + `EvaluatorRegistry` (kind → class dispatch).

Replaces the old `STRUCTURAL = {check_name: callable}` dict + `if/elif kind == 'structural'/'llm_judge'`
chain. New checks just subclass `Evaluator`, set the two ClassVars, and call
`register(MyEvaluator)` on the registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from tracely.domain.evaluation.results import EvalResult, RunContext

# Evaluation levels — mirror `EvaluationLevel` in design 00. Kept as module constants (not
# enums) so the level fields on `EvalResult` / `Evaluator` stay plain strings (the value
# `ClickHouse` actually stores).
RUN = "AGENT_RUN"
TOOL = "TOOL"
GENERATION = "GENERATION"
CHAIN = "CHAIN"


class Evaluator(ABC):
    """One online check.

    `kind` matches `Evaluator.kind` in the Postgres row ("structural" | "llm_judge"). `check`
    is the inner discriminator within a `kind` — for structural evaluators it's
    `config["check"]` (e.g. `"run_outcome"`, `"tool_success"`). LLM-judge evaluators leave
    `check` as `None`: a single class handles every LLM-judge config.
    """

    kind: ClassVar[str]
    check: ClassVar[str | None] = None
    default_level: ClassVar[str] = RUN

    @abstractmethod
    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        """Produce zero or more results. The runner stamps `name` and `level` on each result
        post hoc, so subclasses don't need to set them."""


class EvaluatorRegistry:
    """Resolves `(kind, config.check)` → an Evaluator instance.

    Holds class references (not instances) so each `dispatch` call gets a fresh evaluator —
    fine for now since evaluators are stateless. If a future evaluator becomes expensive to
    construct (loaded model, persistent connection) we cache here.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str | None], type[Evaluator]] = {}

    def register(self, cls: type[Evaluator]) -> type[Evaluator]:
        self._by_key[(cls.kind, cls.check)] = cls
        return cls  # so it can be used as a decorator

    def resolve(self, kind: str, check: str | None) -> type[Evaluator] | None:
        # Try (kind, check) first — needed for structural evaluators that share a kind.
        cls = self._by_key.get((kind, check))
        if cls is not None:
            return cls
        # Fall back to (kind, None) — used by LLM-judge where `check` isn't meaningful.
        return self._by_key.get((kind, None))

    def dispatch(
        self, kind: str, config: dict, score_name: str, level: str, ctx: RunContext
    ) -> list[EvalResult]:
        """Run the matching evaluator and stamp results with the evaluator's score name/level.

        Returns an empty list if no evaluator matches `kind`/`check` (an unknown evaluator
        kind on a project's row is a soft no-op — better than crashing the runner)."""
        config = config or {}
        cls = self.resolve(kind, config.get("check"))
        if cls is None:
            return []
        results = cls().run(ctx, config.get("params") or config or {})
        for r in results:
            r.name = score_name
            if level and r.level == RUN:
                r.level = level
        return results


default_registry = EvaluatorRegistry()


def run_evaluator(
    kind: str, config: dict, score_name: str, level: str, ctx: RunContext
) -> list[EvalResult]:
    """Module-level convenience that uses the default registry. The shim at
    `tracely.evaluators.run_evaluator` re-exports this."""
    return default_registry.dispatch(kind, config, score_name, level, ctx)
