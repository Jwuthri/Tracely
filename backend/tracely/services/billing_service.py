"""Stripe subscription billing — checkout, portal, and the webhook state machine.

The `stripe` import lives here and nowhere else. Everything is driven by webhooks: checkout and
the portal only mint redirect URLs; the plan on the Project row changes exclusively when Stripe
tells us so (idempotent state-sets, safe under replay and out-of-order delivery).

Ordering hazard handled explicitly: `customer.subscription.*` events carry no
`client_reference_id` and can arrive BEFORE `checkout.session.completed` stores the customer id.
Checkout therefore stamps `subscription_data.metadata.project_id` onto the subscription itself,
and the webhook falls back to that metadata when the customer id lookup misses — backfilling the
ids so the next event takes the fast path.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.billing import (
    PLAN_UNLIMITED,
    plan_for_subscription_status,
)
from tracely.infrastructure.db import repositories
from tracely.infrastructure.db.models import Project

log = structlog.get_logger()


def stripe_configured() -> bool:
    return bool(settings.stripe_secret_key and settings.stripe_price_pro)


def _stripe():
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _billing_url() -> str:
    return f"{settings.app_base_url.rstrip('/')}/settings/billing"


def create_checkout_session(session: Session, project_id: str) -> str:
    """A Stripe Checkout URL upgrading this workspace to Pro. Raises ValueError for the
    conditions the router maps to 4xx (already subscribed / unknown project)."""
    project = repositories.project_get(session, project_id)
    if project is None:
        raise ValueError("project not found")
    if (project.subscription_status or "") in ("active", "trialing", "past_due"):
        raise ValueError("already subscribed — manage the existing subscription instead")

    stripe = _stripe()
    customer_id = project.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            name=project.name or project.slug,
            metadata={"project_id": project.id, "project_slug": project.slug},
        )
        customer_id = customer["id"]
        project.stripe_customer_id = customer_id
        session.commit()

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": settings.stripe_price_pro, "quantity": 1}],
        client_reference_id=project.id,
        # Load-bearing: subscription events don't carry client_reference_id, and can arrive
        # before checkout.session.completed — this metadata is the webhook's fallback lookup.
        subscription_data={"metadata": {"project_id": project.id}},
        success_url=f"{_billing_url()}?upgraded=1",
        cancel_url=_billing_url(),
        allow_promotion_codes=True,
    )
    return checkout["url"]


def create_portal_session(session: Session, project_id: str) -> str:
    """A Stripe Billing Portal URL (change card, cancel, invoices). ValueError when the
    workspace has never been through checkout."""
    project = repositories.project_get(session, project_id)
    if project is None or not project.stripe_customer_id:
        raise ValueError("no billing account yet — upgrade first")
    portal = _stripe().billing_portal.Session.create(
        customer=project.stripe_customer_id, return_url=_billing_url()
    )
    return portal["url"]


def verify_webhook(payload: bytes, signature: str):
    """The parsed, signature-verified event — raises on any tampering/malformed input.
    Verification needs the raw request bytes, never a re-serialized body."""
    import stripe

    return stripe.Webhook.construct_event(
        payload, signature, settings.stripe_webhook_secret
    )


def handle_webhook_event(session: Session, event) -> dict:
    """Apply one verified Stripe event. Idempotent state-sets throughout.

    Return contract (the router's response depends on it): normal returns — including unknown
    event types and unknown projects — mean 200 (permanent no-ops must not be redelivered);
    raising means 5xx, so Stripe's retry schedule redelivers after a transient failure instead
    of a paid upgrade being silently swallowed.
    """
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        project = repositories.project_get(session, obj.get("client_reference_id") or "")
        if project is None:
            log.warning("stripe_checkout_unknown_project", ref=obj.get("client_reference_id"))
            return {"handled": False}
        _apply_subscription(
            session, project,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            # Checkout completing means payment succeeded; the subscription.updated that follows
            # carries the authoritative status and converges to the same state.
            status="active",
        )
        return {"handled": True, "plan": project.plan}

    if etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        status = "canceled" if etype.endswith("deleted") else (obj.get("status") or "")
        project = repositories.project_by_stripe_customer(session, obj.get("customer") or "")
        if project is None:
            # Out-of-order delivery: the checkout event hasn't stored the customer id yet.
            project = repositories.project_get(
                session, (obj.get("metadata") or {}).get("project_id") or ""
            )
        if project is None:
            log.warning("stripe_subscription_unknown_project", customer=obj.get("customer"))
            return {"handled": False}
        _apply_subscription(
            session, project,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("id"),
            status=status,
        )
        return {"handled": True, "plan": project.plan}

    return {"handled": False, "ignored": etype}


def _apply_subscription(
    session: Session, project: Project, *, customer_id: str | None,
    subscription_id: str | None, status: str,
) -> None:
    if customer_id:
        project.stripe_customer_id = customer_id
    if subscription_id:
        project.stripe_subscription_id = subscription_id
    project.subscription_status = status
    # Never touch an operator workspace: `unlimited` is set via SQL and owns its plan outright —
    # a stray subscription event against it records the status but must not downgrade the plan.
    if project.plan != PLAN_UNLIMITED:
        project.plan = plan_for_subscription_status(status)
    session.commit()
    log.info(
        "stripe_subscription_applied",
        project_id=project.id, plan=project.plan, status=status,
    )
