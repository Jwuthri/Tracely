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
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
