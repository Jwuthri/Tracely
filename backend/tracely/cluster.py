"""Failure clustering — group similar auto-detected failures into FailureClusters by a
cheap structural signature (Drain3-flavored: failed-evaluator set + masked failure text).

This is the ingest-time stage from design 07/91; the semantic embedding/BERTopic stage
(pgvector + HDBSCAN) is the future upgrade. Human-in-the-loop: clusters are promoted to
regression cases, not auto-promoted.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely.models import ClusterMember, FailureCluster

_MASK = [
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<id>"),  # hex/uuids
    (re.compile(r"\b\d+(\.\d+)?\b"), "<n>"),           # numbers
    (re.compile(r"'[^']*'|\"[^\"]*\""), "<*>"),        # quoted strings
]

_TAXONOMY = {
    "tracely.run.tool_consistency": "execution: tool not executed",
    "tracely.tool.success": "execution: tool error",
    "tracely.run.quality": "output: low quality",
    "tracely.run.latency_ms": "performance: latency",
    "tracely.run.outcome": "execution: error",
}


def _mask(text: str) -> str:
    out = text
    for pat, repl in _MASK:
        out = pat.sub(repl, out)
    return out.strip()


def _signature(failures: list, spans: list[dict]) -> tuple[str, str, str]:
    failed = sorted({f.name for f in failures})
    comments = {_mask(f.comment) for f in failures if f.comment}
    for s in spans:
        if s.get("level") == "ERROR" and s.get("status_message"):
            comments.add(_mask(s["status_message"]))
    comment_list = sorted(c for c in comments if c)

    sig = " || ".join(failed) + " ## " + " || ".join(comment_list)
    label = (comment_list[0] if comment_list else (failed[0] if failed else "failure"))[:200]
    taxonomy = next((_TAXONOMY[n] for n in failed if n in _TAXONOMY), "execution: error")
    return sig, label, taxonomy


def cluster_failure(
    session: Session, project_id: str, agent_id: str, trace_id: str, failures: list, spans: list[dict]
) -> str | None:
    """Upsert the FailureCluster for this failing run and add it as a member. Returns cluster id."""
    if not agent_id or not failures:
        return None
    sig, label, taxonomy = _signature(failures, spans)
    key = hashlib.sha256(sig.encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc)

    cl = session.execute(
        select(FailureCluster).where(
            FailureCluster.project_id == project_id,
            FailureCluster.agent_id == agent_id,
            FailureCluster.cluster_key == key,
        )
    ).scalar_one_or_none()
    if cl is None:
        cl = FailureCluster(
            id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, cluster_key=key,
            label=label, taxonomy=taxonomy, signature=sig[:2000], count=0, status="OPEN",
            first_seen_at=now, last_seen_at=now,
        )
        session.add(cl)
        session.flush()

    member = session.get(ClusterMember, (cl.id, trace_id))
    if member is None:
        session.add(ClusterMember(cluster_id=cl.id, trace_id=trace_id, is_medoid=(cl.count == 0)))
        cl.count = (cl.count or 0) + 1
    cl.last_seen_at = now
    session.commit()
    return cl.id
