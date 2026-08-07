"""Failure clustering — group similar auto-detected failures into `FailureCluster`s using the
cheap structural signature (failed-evaluator set + masked failure text).

Ingest-time stage (design 07/91). The semantic embedding pass lives in
`tracely.services.failure_intel_service`. Human-in-the-loop: clusters are promoted to
regression cases, not auto-promoted.

The value object lives in `tracely.domain.failure.signature` — this service just persists.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.failure.signature import FailureSignature
from tracely.infrastructure.db.models import ClusterMember, FailureCluster

# ponytail: only the N most recently active clusters of an agent are considered for a fuzzy
# merge. Older ones are re-formed by Analyze anyway; raise it if agents run many failure modes.
_MERGE_SCAN_LIMIT = 200


class StructuralClusteringService:
    """Upserts a `FailureCluster` keyed by the masked signature and records the trace as a member."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def cluster_failure(
        self,
        project_id: str,
        agent_id: str,
        trace_id: str,
        eval_failures: list,
        spans: list[dict],
    ) -> str | None:
        """Returns the cluster id (existing or new), or None if there's nothing to cluster."""
        if not agent_id or not eval_failures:
            return None
        sig = FailureSignature.compute(eval_failures, spans)
        now = datetime.now(timezone.utc)

        cl = self._find_existing(project_id, agent_id, sig.key) or self._find_similar(
            project_id, agent_id, sig
        )
        if cl is None:
            try:
                cl = self._create(project_id, agent_id, sig, now)
                self._record_member(cl, trace_id, now)
                self.session.commit()
                return cl.id
            except IntegrityError:
                # Two workers raced on the same brand-new signature; the other insert won the
                # (project, agent, cluster_key) unique constraint. Join its row instead.
                self.session.rollback()
                cl = self._find_existing(project_id, agent_id, sig.key)
                if cl is None:
                    raise

        self._record_member(cl, trace_id, now)
        self.session.commit()
        return cl.id

    # ── internals ─────────────────────────────────────────────────────────────

    def _find_existing(
        self, project_id: str, agent_id: str, cluster_key: str
    ) -> FailureCluster | None:
        return self.session.execute(
            select(FailureCluster).where(
                FailureCluster.project_id == project_id,
                FailureCluster.agent_id == agent_id,
                FailureCluster.cluster_key == cluster_key,
            )
        ).scalar_one_or_none()

    def _find_similar(
        self, project_id: str, agent_id: str, sig: FailureSignature
    ) -> FailureCluster | None:
        """Join an existing cluster whose failure text says the same thing in different words.

        Without this every LLM-judge comment hashes to its own cluster and the list is one row
        per failing trace. IGNOREd clusters are skipped — a merge would resurrect them.
        """
        threshold = settings.cluster_merge_similarity
        if threshold > 1:
            return None  # merging disabled — exact signature only
        candidates = self.session.execute(
            select(FailureCluster)
            .where(
                FailureCluster.project_id == project_id,
                FailureCluster.agent_id == agent_id,
                FailureCluster.status != "IGNORED",
            )
            .order_by(desc(FailureCluster.last_seen_at))
            .limit(_MERGE_SCAN_LIMIT)
        ).scalars()
        return next((c for c in candidates if sig.matches(c.signature or "", threshold)), None)

    def _create(
        self,
        project_id: str,
        agent_id: str,
        sig: FailureSignature,
        now: datetime,
    ) -> FailureCluster:
        cl = FailureCluster(
            id=str(uuid.uuid4()),
            project_id=project_id,
            agent_id=agent_id,
            cluster_key=sig.key,
            label=sig.label,
            taxonomy=sig.taxonomy,
            signature=sig.signature[:2000],
            count=0,
            status="OPEN",
            first_seen_at=now,
            last_seen_at=now,
        )
        self.session.add(cl)
        self.session.flush()
        return cl

    def _record_member(self, cl: FailureCluster, trace_id: str, now: datetime) -> None:
        member = self.session.get(ClusterMember, (cl.id, trace_id))
        if member is None:
            self.session.add(
                ClusterMember(
                    cluster_id=cl.id,
                    trace_id=trace_id,
                    is_medoid=(cl.count == 0),
                )
            )
            cl.count = (cl.count or 0) + 1
        cl.last_seen_at = now
