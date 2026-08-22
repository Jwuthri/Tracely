"""Email sink: one alert to one address via Resend's REST API.

Same contract as the Slack/webhook sinks — sync, best-effort, returns False instead of raising so
a bounced address never crashes the monitor evaluator. Deliberately NOT reusing
`infrastructure/mailer.py`: that one is `async` (it serves the API's invite/reset paths) and the
dispatch path here is sync, called from the Celery worker. Ten lines of httpx beats bridging an
event loop into a worker task.

With `RESEND_API_KEY` unset (the self-host default) this returns False and logs once per send —
the monitor still fires and still records `last_fired_at`, it just has nowhere to mail it.
"""

from __future__ import annotations

import httpx
import structlog

from tracely.config import settings

log = structlog.get_logger()

_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT = 10.0


def send_email_alert(to: str, *, title: str, summary: str, view_url: str = "") -> bool:
    """Mail one alert. Best-effort: True on a 2xx send, False when email is unconfigured or fails."""
    if not to or not settings.resend_api_key:
        if to:
            log.warning("email_notify_unconfigured", to=to)
        return False
    text = f"{title}\n\n{summary}\n" + (f"\nView in Tracely: {view_url}\n" if view_url else "")
    try:
        with httpx.Client(timeout=_TIMEOUT) as cli:
            r = cli.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.email_from,
                    "to": [to],
                    "subject": f"[Tracely] {title}",
                    "text": text,
                },
            )
        if 200 <= r.status_code < 300:
            return True
        log.warning("email_notify_non_2xx", status=r.status_code, body=r.text[:200])
        return False
    except Exception as exc:
        log.warning("email_notify_failed", error=str(exc))
        return False
