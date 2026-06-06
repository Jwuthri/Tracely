"""Failure-intelligence pipeline: embed failing runs -> pgvector -> UMAP+HDBSCAN ->
per-cluster agent (semantic description) -> meta-consolidation agent (Issues).

Triggered on demand ("Analyze failures"). Replaces the cheap signature clusters with
embedding+LLM Issues. Needs OPENAI_API_KEY. All heavy imports are lazy.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tracely import agents, clickhouse
from tracely.config import settings
from tracely.models import ClusterMember, FailureCluster, FailureEmbedding
from tracely.regression import _root, read_trace_spans

log = structlog.get_logger()


def _facts(spans: list[dict]) -> tuple:
    """Pull the failure-relevant facts out of a run's spans, once."""
    root = _root(spans)
    inp = next((s.get("input") for s in spans if s.get("input")), "")
    # the agent's answer: prefer the root/non-tool output; a tool's raw payload is not the answer
    out = (
        root.get("output")
        or next((s.get("output") for s in reversed(spans) if s.get("output") and s.get("type") != "TOOL"), "")
        or next((s.get("output") for s in reversed(spans) if s.get("output")), "")
    )
    requested, executed, errors = set(), set(), []
    for s in spans:
        for t in s.get("tool_call_names") or []:
            if t:
                requested.add(t)
        if s.get("type") == "TOOL" and s.get("name"):
            executed.add(s.get("name"))
        if s.get("level") == "ERROR":
            msg = (s.get("status_message") or "").strip()
            errors.append(f"{s.get('name')}: {msg}" if msg else str(s.get("name")))
    missing = sorted(requested - executed)
    return inp, out, sorted(requested), sorted(executed), errors, missing


def embedding_text(spans: list[dict]) -> str:
    """Terse, mechanism-focused text for the CLUSTERER. The user input / domain is intentionally
    excluded so runs group by failure MECHANISM + error semantics, not by topic — two unrelated
    questions that hit the same bug should land in the same cluster, and the same question failing
    two different ways should not. Error *messages* stay in, so the embedder can sub-group error
    classes semantically (e.g. 'upstream timeout' near 'gateway timed out')."""
    _, out, _, _, errors, missing = _facts(spans)
    lines = []
    if errors:
        lines.append("tool execution error: " + "; ".join(errors))
    if missing:
        lines.append("requested but not executed: " + ", ".join(missing))
    if not lines:
        lines.append("incorrect or low-quality answer: " + (out or "")[:160])
    return " | ".join(lines)


def summarize_failure(spans: list[dict], reasons: list[tuple[str, str]] | None = None) -> str:
    """Full-context block for the ANALYSIS agent + UI display. Leads with the normalized failure
    mode, then the evaluator verdicts that flagged it (ground truth for *why* it failed), the
    tool results, and finally the input/answer context."""
    inp, out, requested, executed, errors, missing = _facts(spans)
    tool_results = [
        f"{s.get('name')} -> {s.get('output')}"
        for s in spans
        if s.get("type") == "TOOL" and s.get("output")
    ]
    modes = []
    if errors:
        modes.append("tool execution error")
    if missing:
        modes.append("requested tool never executed")
    if not modes:
        modes.append("incorrect or low-quality output")

    parts = ["FAILURE MODE: " + "; ".join(modes)]
    if reasons:
        parts.append("Detected by: " + "; ".join(f"{n}: {c}" if c else n for n, c in reasons))
    if errors:
        parts.append("Errors: " + "; ".join(errors))
    if missing:
        parts.append(f"Requested but never executed: {missing}")
    if tool_results:
        parts.append("Tool results: " + " | ".join(tool_results))
    parts += [
        f"Tools requested: {requested} | executed: {executed}",
        f"User input: {inp}",
        f"Agent answer: {out}",
    ]
    return "\n".join(parts)[:3000]


def embed_texts(texts: list[str]) -> list[list[float]]:
    from langchain_openai import OpenAIEmbeddings

    emb = OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
        dimensions=settings.embedding_dim,
    )
    return emb.embed_documents(texts)


def cluster_embeddings(matrix) -> list[int]:
    """Group failure embeddings into clusters (label -1 = noise/outlier).

    Two regimes. For small/moderate sets we cluster directly on cosine distance — robust to
    duplicates and few points. For large, diverse sets we first UMAP-denoise (HDBSCAN degrades
    in raw high-dim space). UMAP is deliberately NOT used on small n: it is a manifold learner
    that, given few or near-identical vectors, scatters them and HDBSCAN then finds phantom
    clusters (it merged distinct failure modes in exactly this way before this guard).
    """
    import numpy as np

    X = np.asarray(matrix, dtype="float64")
    n = len(X)
    if n < 4:
        return [0] * n  # too few to cluster meaningfully -> one group

    import hdbscan

    mcs = settings.fi_min_cluster_size
    if n < settings.fi_umap_min_n:
        from sklearn.metrics.pairwise import cosine_distances

        d = cosine_distances(X).astype("float64")
        labels = hdbscan.HDBSCAN(
            min_cluster_size=mcs, min_samples=1, metric="precomputed"
        ).fit_predict(d)
        return [int(x) for x in labels]

    import umap

    reducer = umap.UMAP(
        n_neighbors=min(15, n - 1), n_components=min(5, n - 1), metric="cosine", random_state=42
    )
    reduced = reducer.fit_transform(X.astype("float32"))
    labels = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=1).fit_predict(reduced)
    return [int(x) for x in labels]


def _delete_clusters(session: Session, cluster_ids: list[str]) -> int:
    """Delete the given FailureClusters and their ClusterMembers (no commit — the caller owns the
    transaction). Returns the number of clusters removed."""
    if not cluster_ids:
        return 0
    session.execute(delete(ClusterMember).where(ClusterMember.cluster_id.in_(cluster_ids)))
    session.execute(delete(FailureCluster).where(FailureCluster.id.in_(cluster_ids)))
    return len(cluster_ids)


def _prune_orphan_clusters(session: Session, project_id: str, keep_agent_ids: set[str]) -> int:
    """Drop every cluster in this project whose agent is NOT being rebuilt this run, so the rebuild
    is project-wide-consistent. _rebuild_agent deletes+rewrites only the agents it visits; an agent
    that has no current failing traces (its runs were fixed, or a reseed gave them new trace_ids) is
    never visited, so without this its clusters persist forever — pointing at wiped traces — and pile
    up across rebuilds. An empty keep set means nothing is failing, so all of the project's clusters
    are pruned. Returns the number of clusters removed."""
    q = select(FailureCluster.id).where(FailureCluster.project_id == project_id)
    if keep_agent_ids:
        q = q.where(FailureCluster.agent_id.not_in(keep_agent_ids))
    orphan_ids = list(session.execute(q).scalars().all())
    n = _delete_clusters(session, orphan_ids)
    if n:
        session.commit()
    return n


def rebuild_clusters(project_id: str) -> dict:
    if not settings.openai_api_key:
        return {"error": "OPENAI_API_KEY not configured"}
    from tracely.db import SyncSessionLocal

    client = clickhouse.get_client()
    # the failing evaluator verdicts ARE the ground truth for why each run failed — pull their
    # reasons so the analysis is grounded in the same signals the eval engine emitted.
    rows = client.query(
        "SELECT trace_id, name, comment FROM scores FINAL WHERE project_id = {p:String} "
        "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = '' LIMIT 5000",
        parameters={"p": project_id},
    ).result_rows
    reasons_by_tid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for tid, name, comment in rows:
        reasons_by_tid[tid].append((name, comment))

    by_agent: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for tid in reasons_by_tid:
        spans = read_trace_spans(client, project_id, tid)
        if not spans:
            continue
        agent_id = _root(spans).get("agent_id")
        if agent_id:
            reasons = reasons_by_tid[tid]
            by_agent[agent_id].append(
                (tid, summarize_failure(spans, reasons), embedding_text(spans))
            )

    issues = 0
    with SyncSessionLocal() as s:
        # drop clusters for agents with no current failing traces, then rebuild the rest — keeps the
        # project consistent instead of accumulating stale clusters from agents that dropped out.
        pruned = _prune_orphan_clusters(s, project_id, set(by_agent))
        for agent_id, items in by_agent.items():
            issues += _rebuild_agent(s, project_id, agent_id, items)
    log.info(
        "fi_rebuild", project_id=project_id, agents=len(by_agent), issues=issues, pruned=pruned
    )
    return {"agents": len(by_agent), "issues": issues, "pruned": pruned}


def _rebuild_agent(session: Session, project_id: str, agent_id: str, items: list[tuple[str, str, str]]) -> int:
    summary_by_tid = {tid: full for tid, full, _ in items}      # full context -> analysis agent + UI
    embed_by_tid = {tid: emb for tid, _, emb in items}          # terse mechanism text -> clusterer

    # 1. embed (cache in failure_embeddings; the vector is keyed to the mechanism text)
    vec_by_tid: dict[str, list[float]] = {}
    to_embed = []
    for tid, _, _ in items:
        row = session.get(FailureEmbedding, tid)
        if row is not None:
            vec_by_tid[tid] = row.embedding
        else:
            to_embed.append(tid)
    if to_embed:
        vecs = embed_texts([embed_by_tid[t] for t in to_embed])
        now = datetime.now(timezone.utc)
        for tid, vec in zip(to_embed, vecs):
            session.merge(FailureEmbedding(
                trace_id=tid, project_id=project_id, agent_id=agent_id,
                summary=summary_by_tid[tid][:4000], embedding=vec, created_at=now,
            ))
            vec_by_tid[tid] = vec
        session.commit()

    # 2. cluster
    tids = [tid for tid, _, _ in items]
    labels = cluster_embeddings([vec_by_tid[t] for t in tids])
    raw: dict[int, list[str]] = defaultdict(list)
    for tid, lab in zip(tids, labels):
        if lab != -1:  # drop HDBSCAN noise
            raw[lab].append(tid)
    if not raw:
        # every failing trace was HDBSCAN noise -> no clusters this run. Clear any this agent kept
        # from a prior rebuild so they don't linger pointing at traces we no longer cover (the same
        # project-wide-consistency invariant _prune_orphan_clusters enforces for dropped agents).
        stale = list(session.execute(
            select(FailureCluster.id).where(
                FailureCluster.project_id == project_id,
                FailureCluster.agent_id == agent_id,
            )
        ).scalars().all())
        if _delete_clusters(session, stale):
            session.commit()
        return 0

    # 3. per-cluster analysis agent
    analyses = []  # (ClusterAnalysis, [tids])
    for ctids in raw.values():
        text = "\n\n".join(f"[trace {t}]\n{summary_by_tid[t]}" for t in ctids[:15])
        analyses.append((agents.analyze_cluster(text), ctids))

    # 4. meta-consolidation agent -> Issues
    if len(analyses) > 1:
        briefs = [
            {"index": i, "title": a.title, "description": a.description, "taxonomy": a.taxonomy}
            for i, (a, _) in enumerate(analyses)
        ]
        groups = agents.consolidate(briefs).issues
    else:
        a0 = analyses[0][0]
        groups = [agents.IssueGroup(title=a0.title, description=a0.description, member_cluster_indices=[0])]

    # 5. replace ALL of this agent's clusters with the consolidated Issues, carrying over the
    #    promotion / ignore state (and linked regression case + first-seen time) from any old
    #    cluster whose traces overlap a new issue. This collapses the cheap signature clusters
    #    into the richer embedding Issues without losing a promotion or duplicating it.
    existing = session.execute(
        select(FailureCluster).where(
            FailureCluster.project_id == project_id,
            FailureCluster.agent_id == agent_id,
        )
    ).scalars().all()
    old_state = []  # (id, status, candidate_case_id, first_seen_at, {trace_ids})
    for ec in existing:
        mtids = set(session.execute(
            select(ClusterMember.trace_id).where(ClusterMember.cluster_id == ec.id)
        ).scalars().all())
        old_state.append((ec.id, ec.status, ec.candidate_case_id, ec.first_seen_at, mtids))
    old_ids = [ec.id for ec in existing]
    if old_ids:
        session.execute(delete(ClusterMember).where(ClusterMember.cluster_id.in_(old_ids)))
        session.execute(delete(FailureCluster).where(FailureCluster.id.in_(old_ids)))
        session.commit()

    def _match(member_tids: set[str], consumed: set[str]):
        # the un-consumed, already-resolved old cluster sharing the most traces with this issue
        best, best_ov = None, 0
        for rec in old_state:
            cid, status, _case, _first, tids = rec
            if cid in consumed or status not in ("PROMOTED", "IGNORED") or not tids:
                continue
            ov = len(member_tids & tids)
            if ov > best_ov and ov >= len(tids) / 2:
                best, best_ov = rec, ov
        if best:
            consumed.add(best[0])
        return best

    now = datetime.now(timezone.utc)
    written = 0
    consumed: set[str] = set()
    for g in groups:
        idxs = [i for i in g.member_cluster_indices if 0 <= i < len(analyses)]
        if not idxs:
            continue
        member_tids: set[str] = set()
        per_trace: dict[str, str] = {}
        for i in idxs:
            analysis, ctids = analyses[i]
            member_tids.update(ctids)
            for ts in analysis.trace_summaries:
                per_trace[ts.trace_id] = ts.summary
        first = analyses[idxs[0]][0]
        match = _match(member_tids, consumed)
        status = match[1] if match else "OPEN"
        case_id = match[2] if match else None
        seen = match[3] if (match and match[3]) else now
        cl = FailureCluster(
            id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id,
            cluster_key=hashlib.sha256(g.title.encode()).hexdigest()[:16],
            label=g.title, taxonomy=first.taxonomy, signature="",
            description=g.description, proposed_fix=first.proposed_fix, severity=first.severity,
            method="embedding", count=len(member_tids), status=status, candidate_case_id=case_id,
            first_seen_at=seen, last_seen_at=now,
        )
        session.add(cl)
        session.flush()
        for j, tid in enumerate(sorted(member_tids)):
            session.add(ClusterMember(
                cluster_id=cl.id, trace_id=tid, is_medoid=(j == 0), summary=per_trace.get(tid, ""),
            ))
        written += 1
    session.commit()
    return written
