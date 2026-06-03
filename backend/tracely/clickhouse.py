"""ClickHouse client + the events insert path.

We deliberately do NOT replicate Langfuse's in-process `ClickhouseWriter` buffer:
Celery tasks are separate processes with no shared in-memory queue, so we lean on
ClickHouse server-side `async_insert` for batching (mirrors the same durability /
throughput goal). See design: 01-steal-and-do-not-copy.md (write path) + canonical §0.
"""

from __future__ import annotations

from typing import Any, Sequence

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from tracely.config import settings


def get_client(database: str | None = None) -> Client:
    """Synchronous client (used by the worker insert path + migrations)."""
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=database if database is not None else settings.clickhouse_database,
    )


async def get_async_client(database: str | None = None):
    """Async client (used by the read API)."""
    return await clickhouse_connect.get_async_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=database if database is not None else settings.clickhouse_database,
    )


def insert_rows(
    client: Client,
    table: str,
    column_names: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> None:
    """Insert column-aligned rows, relying on CH async_insert for server-side batching."""
    if not rows:
        return
    ch_settings: dict[str, Any] = {}
    if settings.clickhouse_async_insert:
        ch_settings = {"async_insert": 1, "wait_for_async_insert": 1}
    client.insert(table, list(rows), column_names=list(column_names), settings=ch_settings)
