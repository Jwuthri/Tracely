"""structlog configuration — call `configure_logging()` once at process start.

Many modules do `structlog.get_logger()` but nothing ever called `structlog.configure()`, so the
observability product had unconfigured observability of itself: output was unstructured and the
level/timestamp/context were inconsistent. This installs one processor chain — a readable console
renderer in dev/local, JSON in deployed envs (docker/prod) for log aggregation.
"""

from __future__ import annotations

import logging

import structlog

from tracely.config import settings


def configure_logging() -> None:
    dev = settings.tracely_env in ("dev", "local", "test")
    shared = [
        structlog.contextvars.merge_contextvars,  # request-id etc. bound per request
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = structlog.dev.ConsoleRenderer() if dev else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
