"""Online evaluator catalog: ABC + per-check classes + dispatch registry.

`Evaluator` is the ABC every check implements. `EvaluatorRegistry` holds the kind→class
mapping the runner uses; it's pre-populated with the built-in checks but tests / future
plugins can register more via `default_registry.register`.
"""

from tracely.domain.evaluation.evaluators.base import (
    CHAIN,
    GENERATION,
    RUN,
    TOOL,
    Evaluator,
    EvaluatorRegistry,
    default_registry,
    run_evaluator,
)
from tracely.domain.evaluation.evaluators.catalog import (
    DEFAULT_JUDGE_PROMPT,
    TEMPLATES,
)
from tracely.domain.evaluation.evaluators.llm_judge import LLMJudgeEvaluator
from tracely.domain.evaluation.evaluators.structural import (
    LatencyEvaluator,
    RequiredToolsEvaluator,
    RunOutcomeEvaluator,
    ToolConsistencyEvaluator,
    ToolSuccessEvaluator,
)
from tracely.domain.evaluation.results import EvalResult, RunContext

__all__ = [
    "Evaluator",
    "EvaluatorRegistry",
    "default_registry",
    "run_evaluator",
    "DEFAULT_JUDGE_PROMPT",
    "TEMPLATES",
    "EvalResult",
    "RunContext",
    "RunOutcomeEvaluator",
    "ToolSuccessEvaluator",
    "ToolConsistencyEvaluator",
    "LatencyEvaluator",
    "RequiredToolsEvaluator",
    "LLMJudgeEvaluator",
    "CHAIN",
    "GENERATION",
    "RUN",
    "TOOL",
]
