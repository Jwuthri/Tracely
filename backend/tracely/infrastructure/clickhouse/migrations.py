"""Tiny ClickHouse migration runner: apply *.up.sql in order. Idempotent (IF NOT EXISTS)."""

from __future__ import annotations

from pathlib import Path

from tracely.config import settings
from tracely.infrastructure.clickhouse.client import get_client

MIGRATIONS_DIR = Path(__file__).parent / "ddl"


def main() -> None:
    admin = get_client(database="default")
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
