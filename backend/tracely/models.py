"""Postgres registry models (SQLAlchemy 2.0). Canonical entities per design 00/09.

MVP slice: Project, IngestKey, Agent, AgentVersion. (EvaluationSuite/Case, FailureCluster,
GateRun/Case come in the next pass — see design/part2-tracely/10-mvp-and-roadmap.md.)
Enums are stored as String here for migration simplicity; values are the canonical sets.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tracely.config import settings
from tracely.db import Base


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


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ingest_keys: Mapped[list["IngestKey"]] = relationship(back_populates="project")
    agents: Mapped[list["Agent"]] = relationship(back_populates="project")


class IngestKey(Base):
    __tablename__ = "ingest_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="ingest_keys")


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


# ── Regression testing (promote a failing trace -> EvaluationCase + replay) ──────


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
    kind: Mapped[str] = mapped_column(String(32), default="REGRESSION")  # REGRESSION|EVAL|E2E
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", "input_digest", name="uq_case_project_agent_inputdigest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    level: Mapped[str] = mapped_column(String(32), default="AGENT_RUN")  # CaseLevel
    title: Mapped[str] = mapped_column(String(512), default="")
    input_digest: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")     # DRAFT|PROMOTED|QUARANTINED|ARCHIVED|UNREPRODUCIBLE
    origin: Mapped[str] = mapped_column(String(32), default="MANUAL")    # PROMOTED_CLUSTER|MANUAL|GENERATED
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
    verdict: Mapped[str] = mapped_column(String(8))  # PASS|FAIL|SKIP
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── CI/CD gate (run an agent's regression suite on a PR -> PASS/FAIL) ─────────────


class GateRun(Base):
    __tablename__ = "gate_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    env: Mapped[str] = mapped_column(String(16), default="ci")
    git_ref: Mapped[str] = mapped_column(String(80), default="")
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="RUNNING")  # RUNNING|PASS|FAIL|ERROR
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    # aggregate metrics over this run's candidate traces (for delta-vs-baseline soft gates)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)  # non-blocking delta warnings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GateCase(Base):
    __tablename__ = "gate_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gate_run_id: Mapped[str] = mapped_column(ForeignKey("gate_runs.id"), index=True)
    evaluation_case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"))
    candidate_trace_id: Mapped[str] = mapped_column(String(64), default="")
    verdict: Mapped[str] = mapped_column(String(8))  # PASS|FAIL|SKIP
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# ── Failure clustering (group similar auto-detected failures) ─────────────────────


class FailureCluster(Base):
    __tablename__ = "failure_clusters"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", "cluster_key", name="uq_cluster_project_agent_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    cluster_key: Mapped[str] = mapped_column(String(64), index=True)  # sha256 of the signature
    label: Mapped[str] = mapped_column(String(256), default="")
    taxonomy: Mapped[str] = mapped_column(String(64), default="")
    signature: Mapped[str] = mapped_column(String(2000), default="")
    description: Mapped[str] = mapped_column(String(4000), default="")   # LLM analysis
    proposed_fix: Mapped[str] = mapped_column(String(4000), default="")  # LLM proposed fix
    severity: Mapped[str] = mapped_column(String(16), default="")        # low|medium|high
    method: Mapped[str] = mapped_column(String(16), default="signature")  # signature|embedding
    count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN|PROMOTED|IGNORED|MERGED
    candidate_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    cluster_id: Mapped[str] = mapped_column(ForeignKey("failure_clusters.id"), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_medoid: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(String(1000), default="")  # LLM per-trace summary
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
