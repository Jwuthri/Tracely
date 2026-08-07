"""Stripe billing: the webhook state machine, endpoint auth, and the config guard.

The webhook handler is unit-tested against a real (SQLite) session — it is the only thing that
may change a workspace's plan, and it must converge under replay and out-of-order delivery.
Router tests go through the app for the parts HTTP owns: signature rejection, role gates, and
the flag/config responses. No test talks to Stripe.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tracely.config import Settings, settings
from tracely.infrastructure.db import models
from tracely.infrastructure.db.base import Base
from tracely.services import billing_service

# ── webhook state machine (unit, real session) ────────────────────────────────


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        eng, tables=[models.Project.__table__, models.UsageCounter.__table__]
    )
    maker = sessionmaker(eng)
    with maker() as s:
        s.add(models.Project(id="p1", slug="acme", name="Acme", source="local"))
        s.commit()
        yield s
    eng.dispose()


def _event(etype: str, obj: dict) -> dict:
    return {"type": etype, "data": {"object": obj}}


def test_checkout_completed_upgrades_and_stores_ids(db):
    out = billing_service.handle_webhook_event(
        db,
        _event(
            "checkout.session.completed",
            {"client_reference_id": "p1", "customer": "cus_1", "subscription": "sub_1"},
        ),
    )
    p = db.get(models.Project, "p1")
    assert out["handled"] is True
    assert (p.plan, p.stripe_customer_id, p.stripe_subscription_id) == ("pro", "cus_1", "sub_1")
    assert p.subscription_status == "active"


def test_checkout_for_unknown_project_is_a_permanent_noop(db):
    out = billing_service.handle_webhook_event(
        db, _event("checkout.session.completed", {"client_reference_id": "nope"})
    )
    assert out == {"handled": False}  # 200 at the router — Stripe must NOT redeliver this


def test_subscription_event_before_checkout_resolves_via_metadata(db):
    """The ordering hazard: subscription.updated can arrive first, when no customer id is
    stored yet. The metadata stamped at checkout-creation is the fallback — and the match
    backfills the ids so the next event takes the fast path."""
    out = billing_service.handle_webhook_event(
        db,
        _event(
            "customer.subscription.updated",
            {"id": "sub_1", "customer": "cus_1", "status": "active",
             "metadata": {"project_id": "p1"}},
        ),
    )
    p = db.get(models.Project, "p1")
    assert out["handled"] is True
    assert p.plan == "pro" and p.stripe_customer_id == "cus_1"


def test_deleted_subscription_downgrades(db):
    billing_service.handle_webhook_event(
        db,
        _event("checkout.session.completed",
               {"client_reference_id": "p1", "customer": "cus_1", "subscription": "sub_1"}),
    )
    billing_service.handle_webhook_event(
        db, _event("customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1"})
    )
    p = db.get(models.Project, "p1")
    assert p.plan == "free" and p.subscription_status == "canceled"


def test_past_due_keeps_the_customer_paid(db):
    """Dunning: a failed card retry moves the subscription to past_due — the workspace stays
    pro until Stripe gives up (canceled/unpaid)."""
    billing_service.handle_webhook_event(
        db,
        _event("checkout.session.completed",
               {"client_reference_id": "p1", "customer": "cus_1", "subscription": "sub_1"}),
    )
    billing_service.handle_webhook_event(
        db,
        _event("customer.subscription.updated",
               {"id": "sub_1", "customer": "cus_1", "status": "past_due"}),
    )
    assert db.get(models.Project, "p1").plan == "pro"


def test_unlimited_plan_is_never_overwritten(db):
    p = db.get(models.Project, "p1")
    p.plan = "unlimited"
    db.commit()
    billing_service.handle_webhook_event(
        db,
        _event("customer.subscription.deleted",
               {"id": "sub_x", "customer": "cus_x", "metadata": {"project_id": "p1"}}),
    )
    assert db.get(models.Project, "p1").plan == "unlimited"  # status recorded, plan untouched


def test_replay_is_idempotent(db):
    ev = _event(
        "checkout.session.completed",
        {"client_reference_id": "p1", "customer": "cus_1", "subscription": "sub_1"},
    )
    billing_service.handle_webhook_event(db, ev)
    billing_service.handle_webhook_event(db, ev)  # Stripe redelivers — same end state
    p = db.get(models.Project, "p1")
    assert (p.plan, p.stripe_customer_id) == ("pro", "cus_1")


def test_unknown_event_type_is_ignored(db):
    out = billing_service.handle_webhook_event(db, _event("invoice.paid", {}))
    assert out["handled"] is False


def test_already_subscribed_checkout_is_refused(db):
    p = db.get(models.Project, "p1")
    p.subscription_status = "active"
    db.commit()
    with pytest.raises(ValueError, match="already subscribed"):
        billing_service.create_checkout_session(db, "p1")


# ── the router (HTTP shapes: signature, roles, flags) ─────────────────────────


@pytest.fixture
def billing_on(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x")
    monkeypatch.setattr(settings, "stripe_price_pro", "price_x")


async def _owner_token(client) -> str:
    r = await client.post(
        "/auth/register", json={"email": "o@x.test", "password": "hunter2-pw"}
    )
    return r.json()["token"]


async def test_webhook_rejects_a_bad_signature(client, billing_on):
    r = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=forged"}
    )
    assert r.status_code == 400


async def test_webhook_404s_when_billing_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    r = await client.post("/api/billing/webhook", content=b"{}")
    assert r.status_code == 404


async def test_webhook_processing_failure_is_5xx_so_stripe_redelivers(
    client, billing_on, monkeypatch
):
    monkeypatch.setattr(billing_service, "verify_webhook", lambda p, s: _event("x", {}))
    monkeypatch.setattr(
        billing_service, "handle_webhook_event",
        lambda s, e: (_ for _ in ()).throw(RuntimeError("pg blip")),
    )
    # The route must NOT swallow this into a 200 — it propagates, and the app's generic
    # exception handler answers 500, which is what makes Stripe redeliver. (The ASGI test
    # transport re-raises server exceptions instead of rendering the 500.)
    with pytest.raises(RuntimeError, match="pg blip"):
        await client.post("/api/billing/webhook", content=b"{}")


async def test_checkout_requires_an_admin_human(client, make_workspace, billing_on):
    # an SDK/CI ingest key has role=None — it must never be able to start a subscription
    _, key = None, (await make_workspace("ws-b", "key-b", "b@x.test"))[2]
    r = await client.post(
        "/api/billing/checkout", headers={"Authorization": f"Bearer {key.key}"}
    )
    assert r.status_code == 403

    # a MEMBER human can't either
    await make_workspace("ws-c", "key-c", "member@x.test", role="MEMBER")
    login = await client.post(
        "/auth/login", json={"email": "member@x.test", "password": "pw-secret"}
    )
    r = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert r.status_code == 403


async def test_checkout_flag_states(client, monkeypatch):
    tok = await _owner_token(client)
    h = {"Authorization": f"Bearer {tok}"}

    monkeypatch.setattr(settings, "billing_enabled", False)
    assert (await client.post("/api/billing/checkout", headers=h)).status_code == 404

    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    assert (await client.post("/api/billing/checkout", headers=h)).status_code == 501


async def test_checkout_returns_the_stripe_url(client, billing_on, monkeypatch):
    tok = await _owner_token(client)
    monkeypatch.setattr(
        billing_service, "create_checkout_session", lambda s, pid: "https://checkout.stripe/x"
    )
    r = await client.post(
        "/api/billing/checkout", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200 and r.json() == {"url": "https://checkout.stripe/x"}


async def test_already_subscribed_is_409_at_the_router(client, billing_on, monkeypatch):
    tok = await _owner_token(client)
    monkeypatch.setattr(
        billing_service, "create_checkout_session",
        lambda s, pid: (_ for _ in ()).throw(ValueError("already subscribed — manage instead")),
    )
    r = await client.post(
        "/api/billing/checkout", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 409


# ── config guard ──────────────────────────────────────────────────────────────


def test_stripe_key_without_webhook_secret_refuses_to_boot():
    with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
        Settings(
            tracely_env="dev", auth_mode="dev",
            stripe_secret_key="sk_x", stripe_webhook_secret="",
        )
    # both set (or neither) is fine
    Settings(tracely_env="dev", auth_mode="dev",
             stripe_secret_key="sk_x", stripe_webhook_secret="whsec_x")
    Settings(tracely_env="dev", auth_mode="dev")
