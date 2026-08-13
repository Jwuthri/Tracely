"""The SDK's read side: pull a workspace's conversations back out of Tracely.

Everything else in this package writes traces. This exists because the alternative every consumer
was hand-rolling — page `/api/sessions`, then one export call per thread — is a loop that silently
truncates the moment someone forgets the paging. The backend streams NDJSON (`GET /api/export`),
so both entry points here are thin: one parses the stream into dicts, one copies the bytes.

    import tracely_sdk as tracely

    for conv in tracely.export_conversations():
        print(conv["thread_id"], conv["turns"])
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any

# Per socket read, not per export: a stream that keeps flowing never trips it, while a connection
# that hangs mid-dump fails instead of pinning a CI job forever.
_TIMEOUT_S = 60


def _open(
    api: str | None,
    key: str | None,
    limit: int,
    from_ts: str | None,
    to_ts: str | None,
    evals: bool,
):
    base = (api or os.environ.get("TRACELY_API") or "http://localhost:8000").strip().rstrip("/")
    token = (key or os.environ.get("TRACELY_KEY") or "tracely_dev_key").strip()
    query = urllib.parse.urlencode(
        # Falsy params are dropped rather than sent empty: `limit=0` means "everything", and
        # `?limit=` would reach the server as a 422 instead.
        {
            k: v
            for k, v in (
                ("limit", limit),
                ("from_ts", from_ts),
                ("to_ts", to_ts),
                ("evals", "true" if evals else ""),
            )
            if v
        }
    )
    url = f"{base}/api/export" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return urllib.request.urlopen(req, timeout=_TIMEOUT_S)


def export_conversations(
    *,
    api: str | None = None,
    key: str | None = None,
    limit: int = 0,
    from_ts: str | None = None,
    to_ts: str | None = None,
    evals: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield every conversation in the workspace, newest first — each one the full object the UI's
    copy button produces (turns, per-turn steps, scores, cost).

    A generator, not a list: a workspace's whole history is the one thing you don't want
    materialised twice, and callers that only need the first N can stop pulling.

    `api`/`key` default to `TRACELY_API` / `TRACELY_KEY`. `limit` caps conversations (0 = all),
    `from_ts`/`to_ts` are ISO-8601 UTC bounds on the trace start, `evals=True` also yields
    Tracely's own internal runs.
    """
    with _open(api, key, limit, from_ts, to_ts, evals) as response:
        for line in response:
            line = line.strip()
            if line:
                yield json.loads(line)


def download_export(
    dest: str | IO[bytes],
    *,
    api: str | None = None,
    key: str | None = None,
    limit: int = 0,
    from_ts: str | None = None,
    to_ts: str | None = None,
    evals: bool = False,
) -> int:
    """Copy the raw NDJSON to a path or an open binary file, returning the bytes written.

    Separate from `export_conversations` so an archive dump never round-trips through
    parse-then-re-serialise — that path is where a float or a datetime quietly changes shape.
    """
    with _open(api, key, limit, from_ts, to_ts, evals) as response, _sink(dest) as fh:
        written = 0
        while chunk := response.read(64 * 1024):
            fh.write(chunk)
            written += len(chunk)
        fh.flush()
        return written


@contextmanager
def _sink(dest: str | IO[bytes]) -> Iterator[IO[bytes]]:
    """A path we open and close; a handle the caller owns and we leave open (closing someone's
    `sys.stdout.buffer` is not ours to do)."""
    if isinstance(dest, str):
        with open(dest, "wb") as fh:
            yield fh
    else:
        yield dest
