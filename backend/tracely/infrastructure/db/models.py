"""Postgres registry models (SQLAlchemy 2.0). Canonical entities per design 00/09.

Enums are stored as String for migration simplicity; values are the canonical sets.
"""

from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tracely.config import settings
from tracely.infrastructure.db.base import Base


class AgentKind(str, enum.Enum):
    SINGLE = "SINGLE"
    MULTI_AGENT = "MULTI_AGENT"
    WORKFLOW = "WORKFLOW"


class AgentRole(str, enum.Enum):
    SUPERVISOR = "SUPERVISOR"
    WORKER = "WORKER"
    PLANNER = "PLANNER"
    EXECUTOR = "EXECUTOR"
    GENERIC = "GENERIC"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_projects_source_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    # tenancy source: "local" (self-host workspace) or "clerk" (org/personal provisioned from Clerk)
    source: Mapped[str] = mapped_column(String(16), default="local")
    # Clerk org_id, or "user:<clerk_user_id>" for a personal workspace; NULL for local single-workspace
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ingest_keys: Mapped[list["IngestKey"]] = relationship(back_populates="project")
    agents: Mapped[list["Agent"]] = relationship(back_populates="project")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="project")


class IngestKey(Base):
    __tablename__ = "ingest_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="ingest_keys")


class User(Base):
    """A human identity. In local mode, `password_hash` is set (argon2). In clerk mode the user is
    upserted from a verified Clerk JWT (`external_id` = Clerk user id, `password_hash` NULL).
    Email/external_id are unique *per source* so the two backends never collide."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_users_source_external"),
        # email is unique only among local accounts (Clerk emails may be unknown/empty/duplicated)
        Index(
            "uq_users_local_email",
            "email",
            unique=True,
            postgresql_where=text("source = 'local'"),
            sqlite_where=text("source = 'local'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(16), default="local")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(Base):
    """Maps a user to a project (the tenant) with a role. The unique (user, project) constraint makes
    Clerk role-sync and `X-Tracely-Project` selection safe idempotent operations."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")  # OWNER | ADMIN | MEMBER
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="memberships")
    project: Mapped[Project] = relationship(back_populates="memberships")


class Invitation(Base):
    """A pending invite to join a project (local mode only; Clerk owns invites in hosted mode).
    Only the sha256 of the raw token is stored; the raw token is shown once at creation."""

    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_invitations_token_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    token_hash: Mapped[str] = mapped_column(String(64))
    invited_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|ACCEPTED|REVOKED|EXPIRED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_agent_project_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    kind: Mapped[str] = mapped_column(String(32), default=AgentKind.SINGLE.value)
    role: Mapped[str] = mapped_column(String(32), default=AgentRole.GENERIC.value)
    framework: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="agents")
    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "config_hash", name="uq_agentversion_agent_confighash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(256), default="")
    git_sha: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="versions")


class EvaluationSuite(Base):
    __tablename__ = "evaluation_suites"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", "slug", name="uq_suite_project_agent_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(256), default="")
    kind: Mapped[str] = mapped_column(String(32), default="REGRESSION")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", "input_digest", name="uq_case_project_agent_inputdigest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    level: Mapped[str] = mapped_column(String(32), default="AGENT_RUN")
    title: Mapped[str] = mapped_column(String(512), default="")
    input_digest: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    origin: Mapped[str] = mapped_column(String(32), default="MANUAL")
    source_trace_id: Mapped[str] = mapped_column(String(64), default="")
    source_span_id: Mapped[str] = mapped_column(String(64), default="")
    agent_version_first_failed: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fixture_bundle_s3_key: Mapped[str] = mapped_column(String(512), default="")
    reference_trajectory: Mapped[dict] = mapped_column(JSON, default=dict)
    assertions: Mapped[dict] = mapped_column(JSON, default=dict)
    match_mode: Mapped[str] = mapped_column(String(16), default="superset")
    tool_args_mode: Mapped[str] = mapped_column(String(16), default="exact")
    fail_to_pass_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationSuiteCase(Base):
    __tablename__ = "evaluation_suite_cases"

    suite_id: Mapped[str] = mapped_column(ForeignKey("evaluation_suites.id"), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"), primary_key=True)
    pinned_case_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseReplay(Base):
    __tablename__ = "case_replays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"), index=True)
    candidate_trace_id: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(8))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GateRun(Base):
    __tablename__ = "gate_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    env: Mapped[str] = mapped_column(String(16), default="ci")
    git_ref: Mapped[str] = mapped_column(String(80), default="")
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="RUNNING")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GateCase(Base):
    __tablename__ = "gate_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gate_run_id: Mapped[str] = mapped_column(ForeignKey("gate_runs.id"), index=True)
    evaluation_case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"))
    candidate_trace_id: Mapped[str] = mapped_column(String(64), default="")
    verdict: Mapped[str] = mapped_column(String(8))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Evaluator(Base):
    """A user-configured online evaluator. The runner loads the project's enabled rows and runs
    them on each trace (filtered by agent/env, sampled). The built-in checks are seeded as editable
    records, not hardcoded defaults."""

    __tablename__ = "evaluators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400), default="")
    kind: Mapped[str] = mapped_column(String(16))
    score_name: Mapped[str] = mapped_column(String(80))
    level: Mapped[str] = mapped_column(String(16), default="AGENT_RUN")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    target_agent: Mapped[str] = mapped_column(String(80), default="")
    target_env: Mapped[str] = mapped_column(String(32), default="")
    sampling: Mapped[float] = mapped_column(Float, default=1.0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FailureCluster(Base):
    __tablename__ = "failure_clusters"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", "cluster_key", name="uq_cluster_project_agent_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    cluster_key: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(256), default="")
    taxonomy: Mapped[str] = mapped_column(String(64), default="")
    signature: Mapped[str] = mapped_column(String(2000), default="")
    description: Mapped[str] = mapped_column(String(4000), default="")
    proposed_fix: Mapped[str] = mapped_column(String(4000), default="")
    severity: Mapped[str] = mapped_column(String(16), default="")
    method: Mapped[str] = mapped_column(String(16), default="signature")
    count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    candidate_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    cluster_id: Mapped[str] = mapped_column(ForeignKey("failure_clusters.id"), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_medoid: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(String(1000), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FailureEmbedding(Base):
    """Cached embedding of a failing run's text (for batch UMAP+HDBSCAN clustering)."""

    __tablename__ = "failure_embeddings"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    summary: Mapped[str] = mapped_column(String(4000), default="")
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetaAnalysis(Base):
    """A cross-metric meta-analysis over an agent's evaluator scores: Spearman correlations +
    z-score outliers (computed deterministically in Python) plus an LLM-written synthesis
    (patterns / recommendations / summary). Scoped per (project, agent); `agent_id` is the events
    agent id (Agent uuid) the analysis covered, or "" for a whole-project analysis. `result` holds
    the full `MetaAnalysisOutput`; `meta` holds run provenance (model, counts, agent slug)."""

    __tablename__ = "meta_analyses"
    __table_args__ = (Index("ix_meta_analyses_project_agent", "project_id", "agent_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    analysis_type: Mapped[str] = mapped_column(String(32), default="agent")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RollingSummary(Base):
    """A per-span ACCUMULATING summary of a conversation: one row per span (step), each holding the
    full compressed summary of every step from the start of the thread up to and including it. The
    last row (highest `step_order`) is the whole-conversation summary. Backs the `@HISTORY` /
    conversation-judge context as a cache (stored compressed history instead of re-sending the raw
    transcript). Generation is idempotent — one row per (project, span)."""

    __tablename__ = "rolling_summaries"
    __table_args__ = (
        UniqueConstraint("project_id", "span_id", name="uq_rolling_summary_project_span"),
        Index("ix_rolling_summaries_thread", "project_id", "thread_id", "step_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    span_id: Mapped[str] = mapped_column(String(64))
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[list] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationAgent(Base):
    """The user-declared agent/tool catalog for a conversation, sent via the SDK
    (`tracely.trace(..., agents=[...])`) as a `tracely.agents` span attribute and captured at ingest.
    One row per (project, thread); `agents` is the declared list
    `[{name, description, tools: {tool_name: {name, description, parameters}}}]`. Distinct from the
    `agents` REGISTRY table (those are observed agent ids); this is optional, richer, user-supplied
    metadata surfaced in the Conversation Agents panel and `@LIST_AGENT`."""

    __tablename__ = "conversation_agents"
    __table_args__ = (
        UniqueConstraint("project_id", "thread_id", name="uq_conversation_agents_project_thread"),
        Index("ix_conversation_agents_project_thread", "project_id", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64))
    agents: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScoreAnnotation(Base):
    """A human label on an evaluator's verdict — the judge-vs-human calibration write path. A reviewer
    agrees/disagrees with a judge score on a target (trace / span / thread); we snapshot the judge
    verdict at label time so agreement is a pure Postgres query. Keyed by the score's natural
    identity (matches the ClickHouse `scores` natural key) + the labeler — one label per user per
    score, upserted."""

    __tablename__ = "score_annotations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "score_name", "evaluation_level", "trace_id", "session_id",
            "observation_id", "labeled_by", name="uq_score_annotations_target_labeler",
        ),
        Index("ix_score_annotations_project_name", "project_id", "score_name"),
        Index("ix_score_annotations_project_trace", "project_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    score_name: Mapped[str] = mapped_column(String(128))
    evaluation_level: Mapped[str] = mapped_column(String(32), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    session_id: Mapped[str] = mapped_column(String(128), default="")
    observation_id: Mapped[str] = mapped_column(String(64), default="")
    judge_verdict: Mapped[str] = mapped_column(String(32), default="")  # snapshot at label time
    human_verdict: Mapped[str] = mapped_column(String(32))  # PASS | FAIL | …
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    labeled_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Monitor(Base):
    """A threshold rule over the regression-loop metrics already in ClickHouse — when its
    `condition` fires over a sliding window, it POSTs to each configured `channel`. Per-monitor
    `min_interval_seconds` dedupes alerts so a noisy condition doesn't page every minute.

    `condition` shape (JSON) — the engine dispatches on `type`:
      `fail_rate_over` — `{score_name, window_minutes, min_samples, threshold}` — fraction of
        FAIL verdicts on a given evaluator over the window must stay BELOW threshold.
      `score_below`    — `{score_name, window_minutes, min_samples, threshold}` — average
        numeric `value` over the window must stay AT OR ABOVE threshold.
      `trace_failure_rate` — `{window_minutes, min_samples, threshold}` — overall failing-trace
        rate (advisory FAILs excluded) over the window must stay BELOW threshold.

    `channels` (JSON list): `[{type: 'slack', url}, {type: 'webhook', url, headers?}]`."""

    __tablename__ = "monitors"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_monitors_project_name"),
        Index("ix_monitors_project_enabled", "project_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400), default="")
    target_agent: Mapped[str] = mapped_column(String(80), default="")
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, default=900)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_summary: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
