"""Transactional email via Resend's REST API (https://resend.com).

Optional integration: when RESEND_API_KEY is unset, `email_enabled()` is False and `send_invite_email`
is a no-op — the caller falls back to surfacing the invite link in the UI, which is the default
dev/self-host behavior. We call the REST API directly with httpx (already a dependency) rather than the
synchronous `resend` SDK, so the send never blocks the async event loop.
"""

from __future__ import annotations

import html as _html

import httpx
import structlog

from tracely.config import settings

log = structlog.get_logger()

_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT = 10.0


def email_enabled() -> bool:
    """True when Resend is configured. Gate any pre-send work (e.g. DB lookups) behind this."""
    return bool(settings.resend_api_key)


def invite_url(raw_token: str) -> str:
    """The accept-invite link — matches the one the frontend builds from window.location.origin."""
    return f"{settings.app_base_url.rstrip('/')}/accept-invite?token={raw_token}"


async def send_invite_email(
    *, to: str, raw_token: str, project_name: str, inviter: str | None
) -> bool:
    """Email the invite link via Resend. Best-effort: returns True on a 2xx send, False when email is
    disabled or the send fails. Never raises — creating the invite must not depend on delivery."""
    if not email_enabled():
        return False
    url = invite_url(raw_token)
    subject = f"You're invited to {project_name} on Tracely"
    text = (
        (f"{inviter} invited you" if inviter else "You've been invited")
        + f" to join {project_name} on Tracely.\n\n"
        f"Accept the invite and set your password:\n{url}\n\n"
        "This link expires in 7 days. If you weren't expecting it, you can ignore this email."
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.email_from,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    "html": _invite_html(project_name=project_name, url=url, inviter=inviter),
                },
            )
    except Exception as e:  # network / timeout — don't block invite creation
        log.warning("invite_email_error", to=to, error=str(e))
        return False
    if resp.status_code >= 300:
        log.warning("invite_email_failed", to=to, status=resp.status_code, body=resp.text[:300])
        return False
    return True


def _invite_html(*, project_name: str, url: str, inviter: str | None) -> str:
    safe_project = _html.escape(project_name)
    who = (
        f'<strong style="color:#e6e9ee">{_html.escape(inviter)}</strong> invited you'
        if inviter
        else "You've been invited"
    )
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#0b0d10;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0b0d10;padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#13161b;border:1px solid #232830;border-radius:12px;padding:32px;">
          <tr><td style="color:#e6e9ee;font-size:18px;font-weight:600;padding-bottom:12px;">Tracely</td></tr>
          <tr><td style="color:#aab2bd;font-size:14px;line-height:1.6;padding-bottom:24px;">
            {who} to join <strong style="color:#e6e9ee">{safe_project}</strong> on Tracely.
          </td></tr>
          <tr><td style="padding-bottom:24px;">
            <a href="{url}" style="display:inline-block;background:#5ec2e0;color:#0b0d10;font-size:14px;font-weight:600;text-decoration:none;padding:12px 22px;border-radius:8px;">Accept invite</a>
          </td></tr>
          <tr><td style="color:#6b7280;font-size:12px;line-height:1.6;">
            Or paste this link into your browser:<br>
            <a href="{url}" style="color:#5ec2e0;word-break:break-all;">{url}</a>
            <br><br>This invite expires in 7 days. If you weren't expecting it, you can ignore this email.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
