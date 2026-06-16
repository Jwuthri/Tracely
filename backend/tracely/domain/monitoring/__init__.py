"""Monitors: threshold rules over the regression-loop metrics already in ClickHouse.

This package owns the **pure** evaluation of a monitor's `condition` against a window's worth
of scores — no I/O. The service in `services.monitoring_service` is the impure orchestrator
(reads from CH, writes Postgres, dispatches to notification channels).
"""
