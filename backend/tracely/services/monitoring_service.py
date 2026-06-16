"""Run a project's (or every project's) enabled monitors: pull the window of samples from
ClickHouse, evaluate each condition (`domain.monitoring.conditions`), dispatch alerts to the
configured channels, and persist the monitor's `last_evaluated_at` / `last_fired_at` /
`last_fired_summary`.

Dedup: a monitor that just fired won't notify again until `min_interval_seconds` has passed
since `last_fired_at` (the engine still RE-evaluates, so `last_evaluated_at` updates every tick).

Async because every ClickHouse read in this codebase is async (via `async_reader`); the
Celery beat wrapper calls into `evaluate_all` via `asyncio.run`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from tracely.api.advisory import advisory_score_names
from tracely.config import settings
from tracely.domain.monitoring.conditions import Sample, Verdict, evaluate_condition
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Monitor
from tracely.infrastructure.notifications import dispatch_alert

log = structlog.get_logger()


def _view_url(monitor: Monitor) -> str:
    """Deep-link to the monitor in the UI — clickable from the alert payload."""
    return f"{settings.app_base_url.rstrip('/')}/monitors/{monitor.id}"


async def _samples_for(monitor: Monitor) -> list[Sample]:
    """Pull the window of samples the monitor's condition needs. The condition `type` decides
    whether we read the score table (per-evaluator) or the trace verdict (project-level)."""
    cond = monitor.condition or {}
    cond_type = str(cond.get("type") or "").strip()
    window_minutes = max(int(cond.get("window_minutes") or 60), 1)
    if cond_type in ("fail_rate_over", "score_below"):
        score_name = str(cond.get("score_name") or "").strip()
        if not score_name:
            return []
        rows = await async_reader.score_samples_in_window(
            monitor.project_id, score_name, window_minutes, monitor.target_agent or ""
        )
        return [Sample(verdict=r["verdict"], value=r["value"]) for r in rows]
    if cond_type == "trace_failure_rate":
        adv = await advisory_score_names(monitor.project_id)
        rows = await async_reader.trace_failure_samples_in_window(
            monitor.project_id, window_minutes, adv, monitor.target_agent or ""
        )
        return [Sample(verdict=r["verdict"], value=None) for r in rows]
    return []


def _should_notify(monitor: Monitor, now: datetime) -> bool:
    """Anti-spam: re-notify only when `min_interval_seconds` has passed since `last_fired_at`."""
    last = monitor.last_fired_at
    if last is None:
        return True
    elapsed = (now - last).total_seconds()
    return elapsed >= float(monitor.min_interval_seconds or 0)


async def _evaluate_monitor(monitor: Monitor, session: Session) -> dict:
    """One tick for one monitor — pull samples, evaluate condition, dispatch alerts, update row.
    Returns a small dict for the caller to log/aggregate."""
    now = datetime.now(timezone.utc)
    try:
        samples = await _samples_for(monitor)
    except Exception as exc:  # CH hiccup must not crash the whole evaluator loop
        log.warning("monitor_samples_failed", monitor_id=monitor.id, error=str(exc))
        return {"id": monitor.id, "status": "samples_error"}

    verdict: Verdict = evaluate_condition(monitor.condition or {}, samples)

    # Always update last_evaluated_at + (a fresh) `last_fired_summary` so the UI shows the
    # current state even when the condition is quiet ("avg score 0.78 (≥0.60) over 23 samples").
    monitor.last_evaluated_at = now
    monitor.last_fired_summary = verdict.summary[:500]
    fired = verdict.fires and _should_notify(monitor, now)
    delivered = {"ok": 0, "fail": 0, "skipped": 0}
    if fired:
        monitor.last_fired_at = now
        delivered = dispatch_alert(
            monitor.channels or [],
            title=f"{monitor.name} fired",
            summary=verdict.summary,
            view_url=_view_url(monitor),
            webhook_payload={
                "source": "tracely",
                "event": "monitor.fired",
                "monitor": {
                    "id": monitor.id, "name": monitor.name, "project_id": monitor.project_id,
                },
                "title": f"{monitor.name} fired",
                "summary": verdict.summary,
                "score": verdict.score,
                "sample_size": verdict.sample_size,
                "view_url": _view_url(monitor),
                "fired_at": now.isoformat(),
            },
        )
    session.commit()
    return {
        "id": monitor.id,
        "fired": fired,
        "evaluated": verdict.skipped_reason == "",
        "skipped_reason": verdict.skipped_reason,
        "sample_size": verdict.sample_size,
        "score": verdict.score,
        "delivered": delivered,
    }


class MonitoringService:
    """Evaluator for the enabled monitors across a project, or across every project (the Celery
    beat fan-out). Stateless — open a sync Session per call (matches the rest of the codebase)."""

    async def evaluate_all(self) -> dict:
        """Every enabled monitor in every project. Called by the beat task."""
        with SyncSessionLocal() as s:
            monitors = repo.enabled_monitors_across_projects(s)
            results = []
            for m in monitors:
                results.append(await _evaluate_monitor(m, s))
        fired = sum(1 for r in results if r.get("fired"))
        return {"monitors": len(results), "fired": fired, "results": results}

    async def evaluate_one(self, project_id: str, monitor_id: str) -> dict | None:
        """One specific monitor (the API `/test` endpoint, e.g. "what does this look like now?")."""
        with SyncSessionLocal() as s:
            monitor = repo.monitor_get(s, project_id, monitor_id)
            if monitor is None:
                return None
            return await _evaluate_monitor(monitor, s)
