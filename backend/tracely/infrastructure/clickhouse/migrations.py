"""Tiny ClickHouse migration runner: apply *.up.sql in order. Idempotent (IF NOT EXISTS)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from clickhouse_connect.driver.client import Client

from tracely.config import settings
from tracely.infrastructure.clickhouse.client import get_client

MIGRATIONS_DIR = Path(__file__).parent / "ddl"

# This is the FIRST thing that touches the network on a deploy (Railway's backend pre-deploy chain,
# docker-compose's migrate step), so it eats every not-ready-yet condition: Railway's private network
# needs a moment to initialize inside a fresh container — internal DNS answers `Name or service not
# known` until it does — and a just-created ClickHouse service may still be booting. Waiting here is
# enough for the whole chain: once the mesh is up, alembic/seeding/S3 resolve too.
# ponytail: one bounded wait in the first step, not a readiness abstraction per dependency.
WAIT_SECONDS = 120.0


def _connect_when_ready(timeout: float = WAIT_SECONDS) -> Client:
    # clickhouse-connect logs a full traceback per failed attempt; while we're deliberately polling a
    # not-ready service that's a screen of noise hiding the one line that matters. Restored after.
    driver_log = logging.getLogger("clickhouse_connect")
    was = driver_log.level
    driver_log.setLevel(logging.CRITICAL)
    try:
        return _poll(timeout)
    finally:
        driver_log.setLevel(was)


def _poll(timeout: float) -> Client:
    deadline = time.monotonic() + timeout
    delay = 1.0
    while True:
        try:
            return get_client(database="default")
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"ClickHouse unreachable at {settings.clickhouse_host}:"
                    f"{settings.clickhouse_port} after {timeout:.0f}s. Check the service is running "
                    "and that CLICKHOUSE_HOST/PORT point at it (on Railway: the ClickHouse service's "
                    "RAILWAY_PRIVATE_DOMAIN, HTTP port 8123)."
                ) from exc
            print(f"clickhouse not ready ({type(exc).__name__}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 8.0)


def main() -> None:
    admin = _connect_when_ready()
    admin.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}")

    client = get_client()
    # Convention: one statement per *.up.sql file. We send the whole file so that
    # semicolons inside `--` comments don't get mis-split into empty statements.
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        sql = sql_file.read_text().strip()
        if sql:
            client.command(sql)
        print(f"applied {sql_file.name}")


if __name__ == "__main__":
    main()
