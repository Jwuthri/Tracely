"""Notification dispatch fan-out tests — no real HTTP, monkeypatch the send fns.

Locks down: each configured channel POSTs once; unknown channel types are silently skipped
(forward-compat); a dead channel doesn't block the other channels; missing URLs are skipped.
"""

from __future__ import annotations

from tracely.infrastructure.notifications import dispatch as d


def _records():
    calls: list[tuple[str, str, dict]] = []

    def slack(url: str, *, title: str, summary: str, view_url: str = "") -> bool:
        calls.append(("slack", url, {"title": title, "summary": summary, "view_url": view_url}))
        return True

    def webhook(url: str, payload: dict, *, headers=None) -> bool:
        calls.append(("webhook", url, {"payload": payload, "headers": headers}))
        return True

    return calls, slack, webhook


def test_dispatch_routes_to_each_channel(monkeypatch):
    calls, slack, webhook = _records()
    monkeypatch.setattr(d, "send_slack", slack)
    monkeypatch.setattr(d, "send_webhook", webhook)

    counts = d.dispatch_alert(
        [
            {"type": "slack", "url": "https://hooks.slack.com/x"},
            {"type": "webhook", "url": "https://example.com/hook", "headers": {"X-Sig": "abc"}},
        ],
        title="Failure rate spike",
        summary="quality FAIL rate 60% (>20%) over 25 samples — 15 failing",
        view_url="https://tracely.app/monitors/abc",
    )
    assert counts == {"ok": 2, "fail": 0, "skipped": 0}
    assert calls[0][0] == "slack" and calls[1][0] == "webhook"
    assert calls[1][2]["headers"] == {"X-Sig": "abc"}


def test_unknown_channel_type_is_skipped(monkeypatch):
    calls, slack, webhook = _records()
    monkeypatch.setattr(d, "send_slack", slack)
    monkeypatch.setattr(d, "send_webhook", webhook)

    counts = d.dispatch_alert(
        [
            {"type": "pagerduty", "url": "https://events.pagerduty.com/x"},
            {"type": "slack", "url": "https://hooks.slack.com/x"},
        ],
        title="t", summary="s",
    )
    assert counts == {"ok": 1, "fail": 0, "skipped": 1}
    assert [c[0] for c in calls] == ["slack"]  # pagerduty was NOT attempted


def test_missing_url_is_skipped_not_failed(monkeypatch):
    _, slack, webhook = _records()
    monkeypatch.setattr(d, "send_slack", slack)
    monkeypatch.setattr(d, "send_webhook", webhook)
    counts = d.dispatch_alert([{"type": "slack", "url": ""}], title="t", summary="s")
    assert counts == {"ok": 0, "fail": 0, "skipped": 1}


def test_one_dead_channel_does_not_block_others(monkeypatch):
    def slack_dead(url, **kw): return False
    def webhook_ok(url, payload, **kw): return True
    monkeypatch.setattr(d, "send_slack", slack_dead)
    monkeypatch.setattr(d, "send_webhook", webhook_ok)
    counts = d.dispatch_alert(
        [
            {"type": "slack", "url": "https://hooks.slack.com/x"},
            {"type": "webhook", "url": "https://example.com/hook"},
        ],
        title="t", summary="s",
    )
    assert counts == {"ok": 1, "fail": 1, "skipped": 0}


def test_empty_channels_returns_zeros(monkeypatch):
    monkeypatch.setattr(d, "send_slack", lambda *a, **k: True)
    monkeypatch.setattr(d, "send_webhook", lambda *a, **k: True)
    assert d.dispatch_alert([], title="t", summary="s") == {"ok": 0, "fail": 0, "skipped": 0}
    assert d.dispatch_alert(None, title="t", summary="s") == {"ok": 0, "fail": 0, "skipped": 0}  # type: ignore[arg-type]


# ── email channel ─────────────────────────────────────────────────────────────
def test_email_channel_uses_to_not_url(monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        d, "send_email_alert", lambda to, **kw: sent.append((to, kw["title"])) or True
    )
    monkeypatch.setattr(d, "send_slack", lambda *a, **k: True)
    counts = d.dispatch_alert(
        [{"type": "email", "to": "oncall@acme.com"}, {"type": "slack", "url": "https://hooks.slack.com/x"}],
        title="Gate failed",
        summary="CI gate FAIL on support-bot",
        view_url="https://tracely.app/gates/abc",
    )
    assert counts == {"ok": 2, "fail": 0, "skipped": 0}
    assert sent == [("oncall@acme.com", "Gate failed")]


def test_email_channel_without_address_is_skipped(monkeypatch):
    # An address is not a URL: `assert_public_url` must not run on it, and a blank one is a skip
    # (config mistake), never a delivery failure.
    monkeypatch.setattr(d, "send_email_alert", lambda *a, **k: True)
    assert d.dispatch_alert([{"type": "email", "to": ""}], title="t", summary="s") == {
        "ok": 0, "fail": 0, "skipped": 1,
    }


def test_email_unconfigured_counts_as_fail_not_crash(monkeypatch):
    # RESEND_API_KEY unset → the sink returns False. The monitor still fired; delivery didn't.
    monkeypatch.setattr(d, "send_email_alert", lambda *a, **k: False)
    assert d.dispatch_alert([{"type": "email", "to": "a@b.com"}], title="t", summary="s") == {
        "ok": 0, "fail": 1, "skipped": 0,
    }
