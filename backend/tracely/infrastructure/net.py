"""Outbound-URL guard: refuse to let a customer point Tracely's own HTTP clients at the inside of
the deployment.

Two features make requests to URLs a workspace member typed in — the agent endpoint a scenario
drives, and a monitor's alert channels. The worker sits on the same network as ClickHouse (whose
HTTP interface runs SQL from a POST body), Postgres, Redis and MinIO, and the agent endpoint even
hands the reply back to the user. Unchecked, `http://clickhouse:8123/?query=SELECT … FROM events`
is a cross-tenant read of the whole store.

`assert_public_url` resolves the host and rejects anything that lands on a loopback, private,
link-local or otherwise non-global address. Applied twice: when the URL is saved (so the UI says
no immediately) and right before each request (so a record written before this existed, or a
hostname whose DNS changed since, is still caught). The check-then-connect gap a DNS rebind could
slip through is accepted; pinning the resolved IP into the connection is the upgrade.

Self-hosters run their agent on localhost; the guard is therefore off outside prod unless
`ALLOW_PRIVATE_URLS` says otherwise (see `settings.private_urls_allowed`)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from tracely.config import settings


class UnsafeURL(ValueError):
    """The URL is malformed, not http(s), or resolves to a non-public address."""


def assert_public_url(url: str) -> None:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL("url must be http(s) with a host")
    if settings.private_urls_allowed:
        return
    host = parts.hostname
    try:
        infos = socket.getaddrinfo(host, parts.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"cannot resolve host {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # `is_global` is False for loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7),
        # link-local (169.254/16 — cloud metadata), multicast, reserved and unspecified.
        if not ip.is_global:
            raise UnsafeURL(f"{host!r} resolves to a non-public address ({ip})")
