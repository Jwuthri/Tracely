"""The evaluation framework — start here.

An evaluator row in Postgres IS a column in the trace table: `kind` picks the implementation
("structural" = deterministic span checks, "llm_judge" = one class covering every rubric),
`level` picks what one result is about, `config` is ONE flat dict of knobs (validated at the
API; reserved runtime keys documented in `base.py`), and `score_name` is the stable key results
persist under.

Lifecycle (every path funnels through `EvaluationService` → `registry.dispatch` → `run()`):

1. Ingest: each trace's settle runs its BATCH trace/step columns (`evaluate_trace`).
2. A debounced whole-thread pass runs when the thread stops growing (`evaluate_thread`):
   CONVERSATION columns once, and SEQUENTIAL message/step columns over every turn in order —
   sequential needs the preceding turns, so it always re-grades the thread from turn 1.
3. On-demand runs (the UI's Play buttons → SSE) and the CI gate reuse the same two entry points.

The level × mode matrix shares three primitives — an item body per level (`prompts.py`), one
chat-vs-paste continuity policy (`llm_judge._chat_id`), one grading tail (`_grade`):

|              | batch (default)              | sequential                                    |
| CONVERSATION | one grade over the thread    | identical — one item, the mode is inert       |
| AGENT_RUN    | each message alone           | one durable conversation over the turns,      |
|              |                              | rebuilt from turn 1 by each thread pass       |
| SPAN/TOOL/…  | each step alone              | one durable conversation over the message's   |
|              |                              | steps, rebuilt per pass                       |

Invariants the rest of the product leans on:
- Results are idempotent: score ids are deterministic per (target, score_name) and sampling is
  deterministic per (trace_id, score_name), so re-evaluation converges (ReplacingMergeTree).
- A failed grade produces NO score (logged + visible in the eval recording), never a fake one.
- Internal (eval/sim) traces are never evaluated — see `domain/introspection.py`.
- PASS/FAIL roll-ups go through `domain/evaluation/verdict.py` and its SQL twin only.

`Evaluator` is the ABC every check implements; `EvaluatorRegistry` maps (kind, check) → class.
Tests / future plugins register more via `default_registry.register`.
"""

from tracely.domain.evaluation.evaluators.base import (
    CHAIN,
    CONVERSATION,
    GENERATION,
    RUN,
    SPAN,
    STEP_LEVELS,
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
    "CONVERSATION",
    "GENERATION",
    "RUN",
    "SPAN",
    "STEP_LEVELS",
    "TOOL",
]
