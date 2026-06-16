"""Slack incoming webhook sink. Stateless POST to a `hooks.slack.com/services/...` URL.

We send `text` (the fallback that drives mobile notifications + search) AND a `blocks` payload
(richer formatting in the channel: a header, the fired summary, and a "View in Tracely" link).
Returns True on a 2xx; logs and returns False on anything else so a flaky channel never crashes
the monitor evaluator.
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()

_TIMEOUT = 5.0


def send_slack(
    url: str,
    *,
    title: str,
    summary: str,
    view_url: str = "",
) -> bool:
    """POST one alert to a Slack incoming webhook. Best-effort."""
    if not url:
        return False
    text = f"🚨 *{title}*\n{summary}" + (f"\n<{view_url}|View in Tracely>" if view_url else "")
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {title}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]
    if view_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Tracely"},
                "url": view_url,
                "style": "primary",
            }],
        })
    try:
        with httpx.Client(timeout=_TIMEOUT) as cli:
            r = cli.post(url, json={"text": text, "blocks": blocks})
        if 200 <= r.status_code < 300:
            return True
        log.warning("slack_notify_non_2xx", status=r.status_code, body=r.text[:200])
        return False
    except Exception as exc:
        log.warning("slack_notify_failed", error=str(exc))
        return False
