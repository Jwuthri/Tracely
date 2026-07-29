"""ClickHouse deletes for the API — the write twin of `async_reader` (same rule: no SQL in routers).

Conversation deletion and the whole-project wipe live here. Uses lightweight `DELETE FROM` (GA
since CH 23.3): rows are masked from every read immediately and dropped on the next merge, so the
UI reflects a delete on the next fetch without waiting for a mutation.
"""

from __future__ import annotations

from tracely.infrastructure.clickhouse.client import get_async_client


async def delete_threads(project_id: str, threads: list[str]) -> int:
    """Delete every trace in these conversation threads, plus their scores. Returns traces removed.

    A "thread" is `conversation_id` when the traces carry one, else the trace_id itself (the
    definition `sessions_overview` groups by), so both forms are matched. Conversation-level
    scores hang off `session_id = thread`, turn/span scores off `trace_id`.

    ponytail: leaves the raw OTLP blobs (keyed per ingest batch, not per trace) and any
    cluster/case rows that reference these traces — cases are promoted regression fixtures with
    their own S3 bundle, and clusters rebuild. Add a cascade when retention/GDPR needs one.
    """
    if not threads:
        return 0
    client = await get_async_client()
    res = await client.query(
        "SELECT DISTINCT trace_id FROM events WHERE project_id = {p:String} "
        "AND (conversation_id IN {t:Array(String)} OR trace_id IN {t:Array(String)})",
        parameters={"p": project_id, "t": threads},
    )
    trace_ids = [r[0] for r in res.result_rows]
    if not trace_ids:
        return 0
    params = {"p": project_id, "ids": trace_ids, "t": threads}
    await client.command(
        "DELETE FROM events WHERE project_id = {p:String} AND trace_id IN {ids:Array(String)}",
        parameters=params,
    )
    await client.command(
        "DELETE FROM scores WHERE project_id = {p:String} "
        "AND (trace_id IN {ids:Array(String)} OR session_id IN {t:Array(String)})",
        parameters=params,
    )
    return len(trace_ids)


async def delete_project_events(project_id: str) -> dict[str, int]:
    """Delete every span and score in a project. Returns the row counts removed.

    Counted before deleting (lightweight DELETE reports no rowcount), so the numbers are what the
    UI shows back — a concurrent ingest could land a span between the count and the delete, which
    is fine: the next wipe gets it.

    ponytail: leaves the raw OTLP blobs in S3, same as `delete_threads` — they're keyed per ingest
    batch, not per project-scan, and re-ingest is idempotent. Empty the bucket if you need it gone.
    """
    client = await get_async_client()
    counts: dict[str, int] = {}
    for table in ("events", "scores"):
        res = await client.query(
            f"SELECT count() FROM {table} WHERE project_id = {{p:String}}",
            parameters={"p": project_id},
        )
        counts[table] = int(res.result_rows[0][0]) if res.result_rows else 0
        if counts[table]:
            await client.command(
                f"DELETE FROM {table} WHERE project_id = {{p:String}}",
                parameters={"p": project_id},
            )
    return {k: v for k, v in counts.items() if v}
