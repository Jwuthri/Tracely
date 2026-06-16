"""Outbound notification sinks for the monitoring engine — Slack incoming webhooks + a
generic webhook POST. Stateless, best-effort: a 4xx/5xx is logged and returned as False; we never
let a flaky channel crash the monitor evaluator."""

from tracely.infrastructure.notifications.dispatch import dispatch_alert
from tracely.infrastructure.notifications.slack import send_slack
from tracely.infrastructure.notifications.webhook import send_webhook

__all__ = ["dispatch_alert", "send_slack", "send_webhook"]
