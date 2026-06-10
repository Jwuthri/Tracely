"""LangGraph agents (create_agent + OpenAI) for failure intelligence.

- analyze_cluster: read a cluster's traces -> semantic title/description/severity/fix + per-trace summaries.
- consolidate:    read all cluster briefs -> merge/split into distinct Issues.

Heavy imports are lazy so the worker/API start even without the LLM stack exercised.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tracely.config import settings


class TraceSummary(BaseModel):
    trace_id: str
    summary: str = Field(description="one short sentence: what went wrong in THIS specific trace")


class ClusterAnalysis(BaseModel):
    title: str = Field(description="short, specific, human-readable issue title")
    description: str = Field(description="2-4 sentences explaining the shared root-cause failure mode")
    severity: str = Field(description="one of: low, medium, high")
    taxonomy: str = Field(description="short category, e.g. 'tool execution', 'prompt conflict', 'hallucination'")
    proposed_fix: str = Field(description="a concrete, actionable suggested fix")
    trace_summaries: list[TraceSummary] = Field(default_factory=list)


class IssueGroup(BaseModel):
    title: str = Field(description="final issue title")
    description: str = Field(description="final issue description")
    member_cluster_indices: list[int] = Field(description="indices of the input clusters that are the SAME issue")


class Consolidation(BaseModel):
    issues: list[IssueGroup]


def _create(response_format):
    from langchain.agents import create_agent  # LangChain v1

    from tracely.infrastructure.llm.provider import get_chat_model

    return create_agent(
        get_chat_model(settings.agent_model), tools=[], response_format=response_format
    )


def analyze_cluster(traces_text: str) -> ClusterAnalysis:
    agent = _create(ClusterAnalysis)
    msg = (
        "You are a senior AI engineer triaging agent failures. The traces below were grouped "
        "together by an embedding clusterer. Identify the SHARED root-cause failure mode, then "
        "produce:\n"
        "- title: short and specific, naming the concrete failure MECHANISM (e.g. 'get_weather "
        "errors with upstream timeout' or 'get_weather requested but never executed'). Never use "
        "vague words like 'issues' or 'problems'.\n"
        "- description: 2-4 sentences stating ONLY what the trace evidence shows. Do not invent "
        "causes, error types, or 'timeouts' that are not present in the text.\n"
        "- severity: low | medium | high.\n"
        "- taxonomy: a short MECHANISM category, e.g. 'tool error', 'tool not executed', "
        "'hallucinated answer', 'wrong output'.\n"
        "- proposed_fix: one concrete fix that matches the actual mechanism.\n"
        "- trace_summaries: one short factual sentence per trace.\n\n" + traces_text
    )
    res = agent.invoke({"messages": [{"role": "user", "content": msg}]})
    return res["structured_response"]


def consolidate(briefs: list[dict]) -> Consolidation:
    agent = _create(Consolidation)
    listing = "\n".join(
        f"[{b['index']}] ({b.get('taxonomy', '')}) {b['title']}: {b['description']}" for b in briefs
    )
    msg = (
        "You are consolidating auto-detected failure clusters into distinct ISSUES. Merge two "
        "clusters ONLY if they share the same failure MECHANISM and root cause. Different "
        "mechanisms are different issues even when they involve the same tool or domain: a tool "
        "that ERRORED is a different issue from a tool that was REQUESTED BUT NEVER EXECUTED, and "
        "both differ from a HALLUCINATED answer. When in doubt, keep them separate. Group the "
        "cluster indices into final issues, each with a clear, specific title and description. "
        "Every cluster index must belong to exactly one issue.\n\n"
        "Clusters:\n" + listing
    )
    res = agent.invoke({"messages": [{"role": "user", "content": msg}]})
    return res["structured_response"]
