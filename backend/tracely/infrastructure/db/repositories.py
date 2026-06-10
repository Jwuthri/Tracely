"""Postgres query functions for the API layer (sync sessions).

EVERY SQLAlchemy query the sync routers/services need lives here — callers open a
`SyncSessionLocal()` (owning the transaction boundary), pass the session in, and keep zero
query-building in route handlers. Functions are grouped by aggregate; they return ORM objects
(or light tuples) — HTTP serialization stays at the edge.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from tracely.infrastructure.db.models import (
    Agent,
    CaseReplay,
    ClusterMember,
    EvaluationCase,
    Evaluator,
    FailureCluster,
    GateCase,
    GateRun,
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


def evaluator_score_names(s: Session, project_id: str) -> set[str]:
    return set(
        s.execute(
            select(Evaluator.score_name).where(Evaluator.project_id == project_id)
        ).scalars()
    )


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
    creation-ordered so sequential chaining is deterministic."""
    q = (
        select(Evaluator)
        .where(Evaluator.project_id == project_id, Evaluator.enabled.is_(True))
        .order_by(Evaluator.created_at)
    )
    if evaluator_ids:
        q = q.where(Evaluator.id.in_(evaluator_ids))
    return [
        {
            "id": r.id, "kind": r.kind, "config": r.config or {},
            "score_name": r.score_name, "level": r.level,
        }
        for r in s.execute(q).scalars()
    ]


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
