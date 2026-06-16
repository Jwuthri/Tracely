"""Generic webhook sink: POST a JSON envelope to a customer-supplied URL.

Envelope shape is stable so customers can write a parser once:
  {
    "source": "tracely",
    "event": "monitor.fired",
    "monitor": {"id", "name", "project_id"},
    "title": str,
    "summary": str,
    "score": float | None,        # the metric value at fire time
    "sample_size": int,
    "view_url": str,              # back-link into the Tracely UI
    "fired_at": iso8601 str,      # UTC
  }

Optional per-channel `headers` (e.g. shared secret, content signature) are merged into the POST.
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()

_TIMEOUT = 5.0


def send_webhook(
    url: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> bool:
    """POST `payload` as JSON to `url`. Best-effort: returns True on a 2xx, False otherwise."""
    if not url:
        return False
    try:
        with httpx.Client(timeout=_TIMEOUT) as cli:
            r = cli.post(url, json=payload, headers=headers or {})
        if 200 <= r.status_code < 300:
            return True
        log.warning("webhook_notify_non_2xx", url=url, status=r.status_code, body=r.text[:200])
        return False
    except Exception as exc:
        log.warning("webhook_notify_failed", url=url, error=str(exc))
        return False
