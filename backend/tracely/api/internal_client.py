"""Call our own FastAPI app in-process, as the caller.

Two agents share this: the MCP server (`api/mcp_server.py`) and the in-app assistant's tools
(`services/assistant_tools.py`). Both are "something operating Tracely on a person's behalf", and
both must be bound by exactly what that person can reach — so neither touches the database. They
re-enter the routers over an ASGI transport (no socket, no second app instance) carrying the
caller's own credentials, which leaves `get_project_id` as the single place scoping happens and
the routers' own validation as the single place a bad write is rejected.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

# Exactly what `get_principal` reads (see `api/auth.py`): an ingest key, or a session JWT plus the
# project it addresses. Never the caller's cookies, host or content-type.
AUTH_HEADERS = ("authorization", "x-tracely-key", "x-tracely-project")


def auth_headers_from(headers: Mapping[str, str]) -> dict[str, str]:
    """The credential headers off an incoming request, lowercased."""
    return {k.lower(): v for k, v in headers.items() if k.lower() in AUTH_HEADERS}


async def api_call(
    headers: dict[str, str],
    method: str,
    path: str,
    *,
    ndjson: bool = False,
    sse: bool = False,
    timeout: float = 60.0,
    **kw: Any,
) -> Any:
    """Issue `method path` against our own app with `headers` as the caller's credentials.

    A non-2xx raises `ValueError` carrying the API's own error body — that text is the whole point:
    handed back to an agent it says precisely which field was wrong, so the validation we already
    wrote for the UI doubles as the agent's feedback loop.
    """
    from tracely.api.main import app  # late: main imports the MCP server to mount it

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tracely.internal", headers=headers
    ) as client:
        r = await client.request(method, path, timeout=timeout, **kw)
    if r.status_code >= 400:
        raise ValueError(f"Tracely API {r.status_code}: {r.text[:500]}")
    if ndjson:  # /api/export streams one JSON object per line, so `r.json()` would choke
        return [json.loads(line) for line in r.text.splitlines() if line.strip()]
    if sse:
        # ASGITransport buffers the whole response, so an SSE endpoint's frames have all arrived
        # by the time we get here — no reader loop, just parse them out of the body.
        return [
            json.loads(line[6:])
            for line in r.text.splitlines()
            if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]")
        ]
    return r.json()
