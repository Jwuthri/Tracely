"""Postgres query functions for the API layer (sync sessions).

EVERY SQLAlchemy query the sync routers/services need lives here — callers open a
`SyncSessionLocal()` (owning the transaction boundary), pass the session in, and keep zero
query-building in route handlers. Functions are grouped by aggregate; they return ORM objects
(or light tuples) — HTTP serialization stays at the edge.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tracely.infrastructure.db.models import (
    Agent,
    CaseReplay,
    ClusterMember,
    ConversationAgent,
    EvaluationCase,
    Evaluator,
    FailureCluster,
    GateCase,
    GateRun,
    MetaAnalysis,
    Monitor,
    RollingSummary,
    ScoreAnnotation,
)

# ── evaluators (= evaluation columns) ─────────────────────────────────────────


def evaluators_list(s: Session, project_id: str) -> list[Evaluator]:
    return list(
        s.execute(
            select(Evaluator)
            .where(Evaluator.project_id == project_id)
            .order_by(Evaluator.created_at)
        ).scalars()
    )


def evaluator_get(s: Session, project_id: str, evaluator_id: str) -> Evaluator | None:
    e = s.get(Evaluator, evaluator_id)
    return e if e and e.project_id == project_id else None


def agent_slug(s: Session, project_id: str, agent_id: str) -> str:
    """The slug for an agent id within a project ("" if unknown) — used to match an evaluator's
    `target_agent` (a human-set slug) against a trace whose spans carry the agent id."""
    if not agent_id:
        return ""
    a = s.get(Agent, agent_id)
    return a.slug if a and a.project_id == project_id else ""


def agents_list(s: Session, project_id: str) -> list[Agent]:
    """A project's registered agents (for the meta-analysis agent selector), newest first."""
    return list(
        s.execute(
            select(Agent)
            .where(Agent.project_id == project_id)
            .order_by(desc(Agent.created_at))
        ).scalars()
    )


def agent_in_project(s: Session, project_id: str, agent_id: str) -> Agent | None:
    """An agent by id, scoped to the project (None if unknown / cross-tenant)."""
    a = s.get(Agent, agent_id)
    return a if a and a.project_id == project_id else None


def evaluator_score_names(s: Session, project_id: str) -> set[str]:
    return set(
        s.execute(
            select(Evaluator.score_name).where(Evaluator.project_id == project_id)
        ).scalars()
    )


def advisory_score_names(s: Session, project_id: str) -> list[str]:
    """Score names of evaluators marked `config.advisory` — a FAIL on these is recorded and shown but
    does NOT flip a trace/turn/session/trend to failing (e.g. the subjective answer-quality judge).
    The per-evaluator replacement for the old hardcoded `name != 'tracely.run.quality'` magic string;
    the read layer excludes these names uniformly (see `domain.evaluation.verdict`)."""
    return [
        r.score_name
        for r in s.execute(
            select(Evaluator).where(Evaluator.project_id == project_id)
        ).scalars()
        if (r.config or {}).get("advisory") is True
    ]


def evaluator_create(
    s: Session,
    project_id: str,
    *,
    name: str,
    description: str,
    kind: str,
    level: str,
    enabled: bool,
    config: dict,
    score_name: str = "",
) -> Evaluator:
    """Insert an evaluator; `score_name` (the stable scores key) is derived from the name when
    not given, and de-collided with a numeric suffix within the project."""
    taken = evaluator_score_names(s, project_id)
    resolved = (score_name or "").strip() or _slug_score_name(name)
    if resolved in taken:
        base, n = resolved, 2
        while f"{base}_{n}"[:80] in taken:
            n += 1
        resolved = f"{base}_{n}"[:80]
    e = Evaluator(
        id=str(uuid4()),
        project_id=project_id,
        name=name.strip(),
        description=description.strip(),
        kind=kind,
        score_name=resolved,
        level=level,
        enabled=enabled,
        config=config or {},
    )
    s.add(e)
    s.commit()
    s.refresh(e)
    return e


def evaluator_update(
    s: Session, project_id: str, evaluator_id: str, patch: dict
) -> Evaluator | None:
    e = evaluator_get(s, project_id, evaluator_id)
    if e is None:
        return None
    for field_name, value in patch.items():
        setattr(e, field_name, value)
    s.commit()
    s.refresh(e)
    return e


def evaluator_delete(s: Session, project_id: str, evaluator_id: str) -> bool:
    e = evaluator_get(s, project_id, evaluator_id)
    if e is None:
        return False
    s.delete(e)
    s.commit()
    return True


def evaluator_enabled_specs(
    s: Session, project_id: str, evaluator_ids: list[str] | None = None
) -> list[dict]:
    """The runner's view of a project's enabled evaluators (optionally narrowed by id),
    creation-ordered so sequential chaining is deterministic.

    When narrowed by `evaluator_ids`, the selection is expanded to also include any enabled
    evaluators it `config.depends_on` (transitively, by `score_name`): a dependent can't be
    graded without its prerequisites' results, so they're pulled into the run and topo-sorted
    to execute first (see `evaluation_service._topo_sort`). Disabled dependencies aren't run —
    the dependent simply grades without that context."""
    all_specs = [
        {
            "id": r.id, "kind": r.kind, "config": r.config or {},
            "score_name": r.score_name, "level": r.level,
            # targeting + sampling — the runner applies these on the auto (on-ingest) run
            "target_agent": r.target_agent or "", "target_env": r.target_env or "",
            "sampling": r.sampling if r.sampling is not None else 1.0,
        }
        for r in s.execute(
            select(Evaluator)
            .where(Evaluator.project_id == project_id, Evaluator.enabled.is_(True))
            .order_by(Evaluator.created_at)
        ).scalars()
    ]
    if not evaluator_ids:
        return all_specs
    by_name = {spec["score_name"]: spec for spec in all_specs}
    wanted = set(evaluator_ids)
    selected_ids = {spec["id"] for spec in all_specs if spec["id"] in wanted}
    frontier = [spec for spec in all_specs if spec["id"] in selected_ids]
    while frontier:  # transitively pull in dependencies so prerequisites run too
        spec = frontier.pop()
        for dep_name in (spec["config"].get("depends_on") or []):
            dep = by_name.get(dep_name)
            if dep and dep["id"] not in selected_ids:
                selected_ids.add(dep["id"])
                frontier.append(dep)
    return [spec for spec in all_specs if spec["id"] in selected_ids]  # creation-ordered


def _slug_score_name(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "metric").lower()).strip("_")
    return f"custom.{(base or 'metric')[:60]}"


# ── regression cases ──────────────────────────────────────────────────────────


def cases_list(s: Session, project_id: str) -> list[EvaluationCase]:
    return list(
        s.execute(
            select(EvaluationCase)
            .where(EvaluationCase.project_id == project_id)
            .order_by(desc(EvaluationCase.created_at))
        ).scalars()
    )


def case_get(s: Session, project_id: str, case_id: str) -> EvaluationCase | None:
    c = s.get(EvaluationCase, case_id)
    return c if c and c.project_id == project_id else None


def case_last_replay(s: Session, case_id: str) -> CaseReplay | None:
    return (
        s.execute(
            select(CaseReplay)
            .where(CaseReplay.case_id == case_id)
            .order_by(desc(CaseReplay.created_at))
            .limit(1)
        ).scalars().first()
    )


def case_replays(s: Session, case_id: str) -> list[CaseReplay]:
    return list(
        s.execute(
            select(CaseReplay)
            .where(CaseReplay.case_id == case_id)
            .order_by(desc(CaseReplay.created_at))
        ).scalars()
    )


# ── failure clusters ──────────────────────────────────────────────────────────


def clusters_list_with_agent(
    s: Session, project_id: str
) -> list[tuple[FailureCluster, str]]:
    return [
        (cl, slug)
        for cl, slug in s.execute(
            select(FailureCluster, Agent.slug)
            .join(Agent, FailureCluster.agent_id == Agent.id)
            .where(FailureCluster.project_id == project_id)
            .order_by(desc(FailureCluster.count), desc(FailureCluster.last_seen_at))
        ).all()
    ]


def cluster_get(s: Session, project_id: str, cluster_id: str) -> FailureCluster | None:
    cl = s.get(FailureCluster, cluster_id)
    return cl if cl and cl.project_id == project_id else None


def cluster_members(s: Session, cluster_id: str) -> list[ClusterMember]:
    return list(
        s.execute(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(desc(ClusterMember.is_medoid), ClusterMember.added_at)
        ).scalars()
    )


def cluster_medoid(s: Session, cluster_id: str) -> ClusterMember | None:
    members = cluster_members(s, cluster_id)
    return members[0] if members else None


# ── gates ─────────────────────────────────────────────────────────────────────


def gates_list_with_agent(s: Session, project_id: str) -> list[tuple[GateRun, str]]:
    return [
        (g, slug)
        for g, slug in s.execute(
            select(GateRun, Agent.slug)
            .join(Agent, GateRun.agent_id == Agent.id)
            .where(GateRun.project_id == project_id)
            .order_by(desc(GateRun.created_at))
        ).all()
    ]


def gate_cases_with_titles(s: Session, gate_id: str) -> list[tuple[GateCase, str]]:
    return [
        (gc, title)
        for gc, title in s.execute(
            select(GateCase, EvaluationCase.title)
            .join(EvaluationCase, GateCase.evaluation_case_id == EvaluationCase.id)
            .where(GateCase.gate_run_id == gate_id)
        ).all()
    ]


# ── search (⌘K registry side) ─────────────────────────────────────────────────


def search_registry(s: Session, project_id: str, q: str) -> list[dict]:
    """Issues, cases, and gates matching the query — pre-shaped for the ⌘K palette."""
    like = f"%{q}%"
    rows: list[dict] = []
    for cl in s.execute(
        select(FailureCluster)
        .where(FailureCluster.project_id == project_id, FailureCluster.label.ilike(like))
        .limit(6)
    ).scalars():
        rows.append({
            "type": "issue", "label": cl.label, "sub": cl.taxonomy or "",
            "href": f"/clusters/{cl.id}",
        })
    for c in s.execute(
        select(EvaluationCase)
        .where(EvaluationCase.project_id == project_id, EvaluationCase.title.ilike(like))
        .limit(6)
    ).scalars():
        rows.append({
            "type": "case", "label": c.title, "sub": c.status, "href": f"/cases/{c.id}",
        })
    for g in s.execute(
        select(GateRun)
        .where(GateRun.project_id == project_id, GateRun.git_ref.ilike(like))
        .order_by(desc(GateRun.created_at))
        .limit(4)
    ).scalars():
        rows.append({
            "type": "gate", "label": g.git_ref or g.id[:8], "sub": g.status,
            "href": f"/gates/{g.id}",
        })
    return rows


# ── dashboard / trends rollups ────────────────────────────────────────────────


def registry_counts(s: Session, project_id: str) -> dict:
    agents = s.execute(
        select(func.count()).select_from(Agent).where(Agent.project_id == project_id)
    ).scalar() or 0
    cases = s.execute(
        select(func.count()).select_from(EvaluationCase).where(EvaluationCase.project_id == project_id)
    ).scalar() or 0
    open_clusters = s.execute(
        select(func.count()).select_from(FailureCluster).where(
            FailureCluster.project_id == project_id, FailureCluster.status == "OPEN"
        )
    ).scalar() or 0
    return {"agents": int(agents), "cases": int(cases), "open_clusters": int(open_clusters)}


def gate_cluster_trends(s: Session, project_id: str) -> dict:
    """The Postgres side of /api/trends: gate pass-rate + per-day outcomes, cluster counts,
    case count, and the MTTR proxy (cluster first-seen → promoted regression case)."""
    from collections import defaultdict

    gates = list(
        s.execute(select(GateRun).where(GateRun.project_id == project_id)).scalars()
    )
    gate_total = len(gates)
    gate_passed = sum(1 for g in gates if g.status == "PASS")
    by_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [passed, failed]
    for g in gates:
        if g.created_at and g.status in ("PASS", "FAIL"):
            by_day[g.created_at.date().isoformat()][0 if g.status == "PASS" else 1] += 1
    gates_daily = [{"date": k, "passed": v[0], "failed": v[1]} for k, v in sorted(by_day.items())]

    clusters = list(
        s.execute(select(FailureCluster).where(FailureCluster.project_id == project_id)).scalars()
    )
    open_c = sum(1 for cl in clusters if cl.status == "OPEN")
    resolved_c = sum(1 for cl in clusters if cl.status == "PROMOTED")
    all_cases = list(
        s.execute(select(EvaluationCase).where(EvaluationCase.project_id == project_id)).scalars()
    )

    # MTTR proxy: hours from a cluster's first-seen to the regression case it was promoted into
    case_created = {c.id: c.created_at for c in all_cases}
    spans: list[float] = []
    for cl in clusters:
        if cl.status == "PROMOTED" and cl.candidate_case_id and cl.first_seen_at:
            created = case_created.get(cl.candidate_case_id)
            if created:
                h = (created - cl.first_seen_at).total_seconds() / 3600.0
                if h >= 0:
                    spans.append(h)
    mttr_hours = round(sum(spans) / len(spans), 1) if spans else None

    return {
        "gates_daily": gates_daily,
        "gate_runs": gate_total,
        "gate_pass_rate": round(gate_passed / gate_total, 3) if gate_total else 0.0,
        "cases": len(all_cases),
        "open_clusters": open_c,
        "resolved_clusters": resolved_c,
        "mttr_hours": mttr_hours,
    }


# ── meta-analyses ─────────────────────────────────────────────────────────────


def meta_analysis_create(
    s: Session, project_id: str, *, agent_id: str, result: dict, meta: dict
) -> MetaAnalysis:
    """Persist a meta-analysis result. A fresh row per run (history is kept); the UI reads the
    latest via `meta_analysis_latest_for_agent`."""
    ma = MetaAnalysis(
        id=str(uuid4()),
        project_id=project_id,
        agent_id=agent_id or "",
        analysis_type="agent",
        result=result or {},
        meta=meta or {},
    )
    s.add(ma)
    s.commit()
    s.refresh(ma)
    return ma


def meta_analysis_latest_for_agent(
    s: Session, project_id: str, agent_id: str
) -> MetaAnalysis | None:
    """The most recent analysis for this (project, agent) — what the panel shows on open."""
    return (
        s.execute(
            select(MetaAnalysis)
            .where(
                MetaAnalysis.project_id == project_id,
                MetaAnalysis.agent_id == (agent_id or ""),
            )
            .order_by(desc(MetaAnalysis.created_at))
            .limit(1)
        ).scalars().first()
    )


def meta_analysis_get(s: Session, project_id: str, analysis_id: str) -> MetaAnalysis | None:
    ma = s.get(MetaAnalysis, analysis_id)
    return ma if ma and ma.project_id == project_id else None


def meta_analysis_delete(s: Session, project_id: str, analysis_id: str) -> bool:
    ma = meta_analysis_get(s, project_id, analysis_id)
    if ma is None:
        return False
    s.delete(ma)
    s.commit()
    return True


# ── rolling summaries ─────────────────────────────────────────────────────────


def rolling_summary_get_by_span(
    s: Session, project_id: str, span_id: str
) -> RollingSummary | None:
    return (
        s.execute(
            select(RollingSummary).where(
                RollingSummary.project_id == project_id, RollingSummary.span_id == span_id
            )
        ).scalars().first()
    )


def rolling_summary_latest_for_thread(
    s: Session, project_id: str, thread_id: str
) -> RollingSummary | None:
    """The highest-step_order row = the whole-conversation summary."""
    return (
        s.execute(
            select(RollingSummary)
            .where(
                RollingSummary.project_id == project_id, RollingSummary.thread_id == thread_id
            )
            .order_by(desc(RollingSummary.step_order), desc(RollingSummary.created_at))
            .limit(1)
        ).scalars().first()
    )


def rolling_summary_latest_before(
    s: Session, project_id: str, thread_id: str, step_order: int
) -> RollingSummary | None:
    """The accumulated summary strictly before `step_order` — seeds continued accumulation."""
    return (
        s.execute(
            select(RollingSummary)
            .where(
                RollingSummary.project_id == project_id,
                RollingSummary.thread_id == thread_id,
                RollingSummary.step_order < step_order,
            )
            .order_by(desc(RollingSummary.step_order))
            .limit(1)
        ).scalars().first()
    )


def rolling_summary_list_for_thread(
    s: Session, project_id: str, thread_id: str
) -> list[RollingSummary]:
    return list(
        s.execute(
            select(RollingSummary)
            .where(
                RollingSummary.project_id == project_id, RollingSummary.thread_id == thread_id
            )
            .order_by(RollingSummary.step_order)
        ).scalars()
    )


def rolling_summary_create(
    s: Session,
    project_id: str,
    *,
    thread_id: str,
    trace_id: str,
    span_id: str,
    step_order: int,
    summary: list,
    token_count: int,
    meta: dict,
) -> RollingSummary:
    """Insert one step's accumulated summary. Race-safe: a concurrent writer that already inserted
    this span (unique project+span) makes us roll back and return the existing row."""
    rs = RollingSummary(
        id=str(uuid4()),
        project_id=project_id,
        thread_id=thread_id,
        trace_id=trace_id or "",
        span_id=span_id,
        step_order=step_order,
        summary=summary or [],
        token_count=token_count,
        meta=meta or {},
    )
    s.add(rs)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        existing = rolling_summary_get_by_span(s, project_id, span_id)
        if existing is not None:
            return existing
        raise
    s.refresh(rs)
    return rs


def rolling_summary_delete_for_thread(s: Session, project_id: str, thread_id: str) -> int:
    """Drop a thread's summaries (force-regenerate). Returns rows removed."""
    rows = rolling_summary_list_for_thread(s, project_id, thread_id)
    for r in rows:
        s.delete(r)
    s.commit()
    return len(rows)


# ── conversation agents (user-declared catalog) ───────────────────────────────


def conversation_agents_get(
    s: Session, project_id: str, thread_id: str
) -> ConversationAgent | None:
    return (
        s.execute(
            select(ConversationAgent).where(
                ConversationAgent.project_id == project_id,
                ConversationAgent.thread_id == thread_id,
            )
        ).scalars().first()
    )


def conversation_agents_upsert(
    s: Session, project_id: str, *, thread_id: str, agents: list, meta: dict | None = None
) -> ConversationAgent:
    """Insert or replace a conversation's declared agent catalog (latest wins per thread)."""
    row = conversation_agents_get(s, project_id, thread_id)
    if row is None:
        row = ConversationAgent(
            id=str(uuid4()),
            project_id=project_id,
            thread_id=thread_id,
            agents=agents or [],
            meta=meta or {},
        )
        s.add(row)
    else:
        row.agents = agents or []
        if meta is not None:
            row.meta = meta
    s.commit()
    s.refresh(row)
    return row


# ── score annotations (judge-vs-human calibration) ──────────────────────────────
def _annotation_key(q, project_id, score_name, evaluation_level, trace_id, session_id, observation_id, labeled_by):
    return q.where(
        ScoreAnnotation.project_id == project_id,
        ScoreAnnotation.score_name == score_name,
        ScoreAnnotation.evaluation_level == evaluation_level,
        ScoreAnnotation.trace_id == trace_id,
        ScoreAnnotation.session_id == session_id,
        ScoreAnnotation.observation_id == observation_id,
        ScoreAnnotation.labeled_by == labeled_by,
    )


def score_annotation_upsert(
    s: Session,
    project_id: str,
    *,
    score_name: str,
    human_verdict: str,
    evaluation_level: str = "",
    trace_id: str = "",
    session_id: str = "",
    observation_id: str = "",
    judge_verdict: str = "",
    note: str | None = None,
    labeled_by: str = "",
) -> ScoreAnnotation:
    """Insert or replace one reviewer's label on a judge score (keyed by the score's natural identity
    + labeler). `judge_verdict` is snapshotted so agreement reflects what the human reviewed."""
    row = _annotation_key(
        select(ScoreAnnotation), project_id, score_name, evaluation_level, trace_id, session_id,
        observation_id, labeled_by,
    )
    row = s.execute(row).scalar_one_or_none()
    if row is None:
        row = ScoreAnnotation(
            id=str(uuid4()), project_id=project_id, score_name=score_name,
            evaluation_level=evaluation_level, trace_id=trace_id, session_id=session_id,
            observation_id=observation_id, judge_verdict=judge_verdict,
            human_verdict=human_verdict, note=note, labeled_by=labeled_by,
        )
        s.add(row)
    else:
        row.judge_verdict = judge_verdict
        row.human_verdict = human_verdict
        row.note = note
    s.commit()
    s.refresh(row)
    return row


def score_annotation_delete(
    s: Session,
    project_id: str,
    *,
    score_name: str,
    evaluation_level: str = "",
    trace_id: str = "",
    session_id: str = "",
    observation_id: str = "",
    labeled_by: str = "",
) -> bool:
    """Remove a reviewer's label (clearing it). Returns whether a row was deleted."""
    row = _annotation_key(
        select(ScoreAnnotation), project_id, score_name, evaluation_level, trace_id, session_id,
        observation_id, labeled_by,
    )
    row = s.execute(row).scalar_one_or_none()
    if row is None:
        return False
    s.delete(row)
    s.commit()
    return True


def score_annotations_for_trace(
    s: Session, project_id: str, *, trace_id: str = "", session_id: str = "",
    labeled_by: str | None = None,
) -> list[ScoreAnnotation]:
    """Existing labels on a trace and/or its thread (optionally just one reviewer's) — used to render
    the current annotation state in the UI."""
    q = select(ScoreAnnotation).where(ScoreAnnotation.project_id == project_id)
    keys = []
    if trace_id:
        keys.append(ScoreAnnotation.trace_id == trace_id)
    if session_id:
        keys.append(ScoreAnnotation.session_id == session_id)
    if keys:
        q = q.where(or_(*keys))
    if labeled_by is not None:
        q = q.where(ScoreAnnotation.labeled_by == labeled_by)
    return list(s.execute(q).scalars().all())


def score_annotations_for_project(
    s: Session, project_id: str, score_name: str | None = None
) -> list[ScoreAnnotation]:
    """All labels in a project (optionally one evaluator) — the input to the agreement computation."""
    q = select(ScoreAnnotation).where(ScoreAnnotation.project_id == project_id)
    if score_name:
        q = q.where(ScoreAnnotation.score_name == score_name)
    return list(s.execute(q.order_by(desc(ScoreAnnotation.updated_at))).scalars().all())


# ── monitors ──────────────────────────────────────────────────────────────────


def monitors_list(s: Session, project_id: str) -> list[Monitor]:
    """A project's monitors, oldest first (CRUD UI ordering matches creation)."""
    return list(
        s.execute(
            select(Monitor).where(Monitor.project_id == project_id).order_by(Monitor.created_at)
        ).scalars()
    )


def monitor_get(s: Session, project_id: str, monitor_id: str) -> Monitor | None:
    m = s.get(Monitor, monitor_id)
    return m if m and m.project_id == project_id else None


def monitor_create(
    s: Session,
    project_id: str,
    *,
    name: str,
    description: str,
    target_agent: str,
    condition: dict,
    channels: list,
    enabled: bool,
    min_interval_seconds: int,
) -> Monitor:
    m = Monitor(
        id=str(uuid4()),
        project_id=project_id,
        name=name.strip(),
        description=description.strip(),
        target_agent=(target_agent or "").strip(),
        condition=condition or {},
        channels=channels or [],
        enabled=enabled,
        min_interval_seconds=max(int(min_interval_seconds or 0), 0),
    )
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def monitor_update(
    s: Session, project_id: str, monitor_id: str, patch: dict
) -> Monitor | None:
    m = monitor_get(s, project_id, monitor_id)
    if m is None:
        return None
    for field_name, value in patch.items():
        setattr(m, field_name, value)
    s.commit()
    s.refresh(m)
    return m


def monitor_delete(s: Session, project_id: str, monitor_id: str) -> bool:
    m = monitor_get(s, project_id, monitor_id)
    if m is None:
        return False
    s.delete(m)
    s.commit()
    return True


def enabled_monitors_across_projects(s: Session) -> list[Monitor]:
    """Every enabled monitor across every project — the worker's fan-out input. Cheap (small
    table, indexed `(project_id, enabled)`)."""
    return list(
        s.execute(select(Monitor).where(Monitor.enabled.is_(True))).scalars()
    )
