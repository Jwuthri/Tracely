"""The recommended evaluator catalog — seeded into a project's `evaluators` table as editable
records (see `services.seeding_service`). Edits to a record persist; the seeder is idempotent
by `score_name`."""

from __future__ import annotations

DEFAULT_JUDGE_PROMPT = (
    "You are grading an AI agent's answer for correctness, faithfulness to its tool results, and "
    "helpfulness. Give a LOW score to answers that are unhelpful, self-contradictory, absurd, or "
    "that state facts not supported by (or contradicting) the tool results."
)

TEMPLATES = [
    {"name": "Run outcome", "kind": "structural", "score_name": "tracely.run.outcome", "level": "AGENT_RUN",
     "description": "Fails if any step in the run errored.", "config": {"check": "run_outcome"}, "recommended": True},
    {"name": "Tool success", "kind": "structural", "score_name": "tracely.tool.success", "level": "TOOL",
     "description": "Fails if a tool call errored.", "config": {"check": "tool_success"}, "recommended": True},
    {"name": "Tool consistency", "kind": "structural", "score_name": "tracely.run.tool_consistency",
     "level": "AGENT_RUN", "recommended": True,
     "description": "Fails if the model requested a tool that never executed (a silent failure).",
     "config": {"check": "tool_consistency"}},
    {"name": "Latency", "kind": "structural", "score_name": "tracely.run.latency_ms", "level": "AGENT_RUN",
     "description": "Fails if the run exceeds the latency budget.", "recommended": True,
     "config": {"check": "latency", "params": {"budget_ms": 60000}}},
    {"name": "Answer quality · LLM judge", "kind": "llm_judge", "score_name": "tracely.run.quality",
     "level": "AGENT_RUN", "recommended": True,
     "description": "An LLM grades the answer for correctness and faithfulness to the tool results.",
     "config": {"prompt": DEFAULT_JUDGE_PROMPT, "threshold": 0.6}},
    {"name": "Required tools", "kind": "structural", "score_name": "tracely.run.required_tools",
     "level": "AGENT_RUN", "recommended": False,
     "description": "Fails if specific tools weren't called.",
     "config": {"check": "required_tools", "params": {"tools": []}}},
]
