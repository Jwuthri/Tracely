"""Hosted-cloud billing: usage snapshot, Stripe checkout/portal, and the webhook.

Always mounted (the frontend probes `/api/billing/usage` unconditionally); each endpoint checks
its own flags — usage answers `billing_enabled: false` for self-hosters, checkout/portal 404
when billing is off and 501 when Stripe isn't configured.

Auth is deliberately uneven, per endpoint:
- usage: any project principal (the page and banner read it).
- checkout/portal: OWNER/ADMIN humans only — ingest keys have `role=None`, so an SDK credential
  can never start a paid subscription. The subscription belongs to the caller's ORGANIZATION,
  which is what a workspace's quota is charged against.
- webhook: NO bearer auth (precedent: `share.py`). Stripe authenticates with `Stripe-Signature`
  over the raw body bytes; a bad signature is 400, and transient processing failures are 5xx so
  Stripe's retry schedule redelivers (a swallowed DB blip must not eat a paid upgrade).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id, require_role
from tracely.auth import Principal
from tracely.config import settings
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.session import get_session
from tracely.services import billing_service, quota_service

router = APIRouter(prefix="/api")


@router.get("/billing/usage")
async def billing_usage(
    project_id: str = Depends(get_project_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """`{billing_enabled, plan, period, traces_used, trace_limit}` — `trace_limit` is null for
    the unlimited plan (the meter renders nothing to fill)."""
    return await quota_service.usage_snapshot(project_id, session)


def _require_billing() -> None:
    if not settings.billing_enabled:
        raise HTTPException(status_code=404, detail="billing is not enabled on this deployment")
    if not billing_service.stripe_configured():
        raise HTTPException(status_code=501, detail="billing is not configured (Stripe keys unset)")


def _organization_id(principal: Principal) -> str:
    """The account being billed. Machine principals never get here (`require_role` rejects a
    `role=None` ingest key first); an org-less project means a CLI-seeded/dev workspace."""
    if not principal.organization_id:
        raise HTTPException(400, "this workspace has no organization to bill")
    return principal.organization_id


@router.post("/billing/checkout")
async def billing_checkout(
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
) -> dict:
    """A Stripe Checkout URL upgrading this organization to Pro. 409 when already subscribed."""
    _require_billing()
    organization_id = _organization_id(principal)

    def work() -> str:
        with SyncSessionLocal() as s:
            return billing_service.create_checkout_session(s, organization_id)

    try:
        return {"url": await run_in_threadpool(work)}
    except ValueError as exc:
        raise HTTPException(
            status_code=409 if "already" in str(exc) else 404, detail=str(exc)
        ) from None
    except Exception as exc:  # Stripe API failure — theirs, not ours
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}") from None


@router.post("/billing/portal")
async def billing_portal(
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
) -> dict:
    """A Stripe Billing Portal URL — change card, cancel, download invoices."""
    _require_billing()
    organization_id = _organization_id(principal)

    def work() -> str:
        with SyncSessionLocal() as s:
            return billing_service.create_portal_session(s, organization_id)

    try:
        return {"url": await run_in_threadpool(work)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}") from None


@router.post("/billing/webhook")
async def billing_webhook(request: Request) -> dict:
    """Stripe's event feed. Signature-authenticated — see the module docstring."""
    if not settings.billing_enabled or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=404, detail="billing is not enabled")
    payload = await request.body()  # raw bytes — signature verification demands them
    signature = request.headers.get("stripe-signature", "")
    try:
        event = billing_service.verify_webhook(payload, signature)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid signature") from None

    def work() -> dict:
        with SyncSessionLocal() as s:
            return billing_service.handle_webhook_event(s, event)

    # No try/except: a processing failure must surface as a 5xx so Stripe redelivers.
    return await run_in_threadpool(work)
