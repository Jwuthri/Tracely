"""Fan an alert out across a monitor's configured channels — one place per-channel routing
lives, so the service + the API's `/test` endpoint share the exact same dispatch logic.

`channels` is the `Monitor.channels` JSON list. Each entry has `type` ∈ {`slack`, `webhook`,
`email`} plus its own address: `url` (+ optional `headers`) for the two POST sinks, `to` for
email. Unknown channel types are logged and skipped (forward-compat: adding PagerDuty later is
one entry here, no migration).
"""

from __future__ import annotations

import structlog

from tracely.infrastructure.notifications.email import send_email_alert
from tracely.infrastructure.notifications.slack import send_slack
from tracely.infrastructure.notifications.webhook import send_webhook
from tracely.infrastructure.net import UnsafeURL, assert_public_url

log = structlog.get_logger()


def dispatch_alert(
    channels: list[dict],
    *,
    title: str,
    summary: str,
    view_url: str = "",
    webhook_payload: dict | None = None,
) -> dict[str, int]:
    """Send one alert across every configured channel. Returns `{ok, fail, skipped}` counts so
    the caller can log "delivered to 2 of 3 channels" (or "skipped 1 unknown type")."""
    ok = fail = skipped = 0
    for ch in channels or []:
        ctype = str(ch.get("type") or "").lower()
        if ctype == "email":
            # No SSRF check here: an address is not a URL we fetch, it is a recipient Resend
            # delivers to.
            to = str(ch.get("to") or "").strip()
            if not to:
                skipped += 1
                continue
            if send_email_alert(to, title=title, summary=summary, view_url=view_url):
                ok += 1
            else:
                fail += 1
            continue
        url = str(ch.get("url") or "")
        if not url:
            skipped += 1
            continue
        try:
            assert_public_url(url)  # a channel is a POST from inside our network
        except UnsafeURL as exc:
            log.warning("channel_url_rejected", url=url, error=str(exc))
            skipped += 1
            continue
        if ctype == "slack":
            sent = send_slack(url, title=title, summary=summary, view_url=view_url)
        elif ctype == "webhook":
            payload = webhook_payload or {"title": title, "summary": summary}
            sent = send_webhook(url, payload, headers=ch.get("headers") or None)
        else:
            log.warning("unknown_channel_type", type=ctype)
            skipped += 1
            continue
        if sent:
            ok += 1
        else:
            fail += 1
    return {"ok": ok, "fail": fail, "skipped": skipped}
