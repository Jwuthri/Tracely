"""organizations: the account tier above workspaces.

People become members of an ORGANIZATION; access to a workspace is derived from membership in
that workspace's org. Billing (plan + Stripe) and the monthly trace quota move up here too, so a
company buys one subscription for several workspaces instead of one per workspace.

The backfill is the load-bearing part: every existing user must come out the other side with
exactly the access they had. It groups today's projects by their owner (`billing_owner_id`, else
the earliest OWNER membership) into one org per owner — which preserves migration 0022's quota
pooling semantics exactly — and replays `memberships` into `organization_memberships`, keeping
the strongest role when a user was in several of an owner's projects. Projects with no human
member at all (CLI-seeded, dev mode) stay org-less, exactly as they were unreachable-by-login
before.

`memberships` and the `projects` billing columns are deliberately NOT dropped here: a rollback to
the previous image must still find its data. A later migration removes them.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-07
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from uuid import uuid4

from alembic import op
from sqlalchemy import text

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_RANK = {"MEMBER": 0, "ADMIN": 1, "OWNER": 2}
_PLAN_RANK = {"free": 0, "pro": 1, "unlimited": 2}


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (base or "org")[:96]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id                     VARCHAR(36)  NOT NULL PRIMARY KEY,
            name                   VARCHAR(256) NOT NULL,
            slug                   VARCHAR(128) NOT NULL UNIQUE,
            kind                   VARCHAR(16)  NOT NULL DEFAULT 'personal',
            plan                   VARCHAR(16)  NOT NULL DEFAULT 'free',
            stripe_customer_id     VARCHAR(64),
            stripe_subscription_id VARCHAR(64),
            subscription_status    VARCHAR(32),
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organizations_stripe_customer_id "
        "ON organizations (stripe_customer_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_memberships (
            id              VARCHAR(36) NOT NULL PRIMARY KEY,
            organization_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id         VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role            VARCHAR(16) NOT NULL DEFAULT 'MEMBER',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_org_membership_org_user UNIQUE (organization_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_memberships_user_id "
        "ON organization_memberships (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_memberships_org_id "
        "ON organization_memberships (organization_id)"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id VARCHAR(36) "
        "REFERENCES organizations(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects (organization_id)"
    )
    op.execute(
        "ALTER TABLE invitations ADD COLUMN IF NOT EXISTS organization_id VARCHAR(36) "
        "REFERENCES organizations(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_invitations_organization_id "
        "ON invitations (organization_id)"
    )
    # Invites now target an org; the old column stays for history but must accept NULL.
    op.execute("ALTER TABLE invitations ALTER COLUMN project_id DROP NOT NULL")

    _backfill()


def _backfill() -> None:
    """Group existing projects into one org per owner and replay memberships. Idempotent: does
    nothing for projects already assigned to an org."""
    conn = op.get_bind()

    projects = conn.execute(
        text(
            """
            SELECT p.id, p.name, p.slug, p.plan, p.billing_owner_id, p.stripe_customer_id,
                   p.stripe_subscription_id, p.subscription_status
            FROM projects p
            WHERE p.organization_id IS NULL
            ORDER BY p.created_at, p.id
            """
        )
    ).mappings().all()
    if not projects:
        return

    members = conn.execute(
        text("SELECT project_id, user_id, role FROM memberships ORDER BY created_at, id")
    ).mappings().all()
    by_project: dict[str, list[dict]] = {}
    for m in members:
        by_project.setdefault(m["project_id"], []).append(dict(m))

    def owner_of(project) -> str | None:
        if project["billing_owner_id"]:
            return project["billing_owner_id"]
        rows = by_project.get(project["id"]) or []
        owners = [r for r in rows if r["role"] == "OWNER"]
        return (owners or rows)[0]["user_id"] if (owners or rows) else None

    # owner user id -> the org they get. Projects with no member at all stay org-less.
    orgs: dict[str, dict] = {}
    for p in projects:
        owner = owner_of(p)
        if owner is None:
            continue
        org = orgs.get(owner)
        if org is None:
            org = orgs[owner] = {
                "id": str(uuid4()),
                "name": p["name"] or "Workspace",
                "slug": f"{_slugify(p['slug'] or p['name'])}-{secrets.token_hex(3)}",
                "projects": [],
                "plan": "free",
                "stripe_customer_id": None,
                "stripe_subscription_id": None,
                "subscription_status": None,
            }
        org["projects"].append(p)
        # A user's best plan wins; carry the Stripe ids from whichever project holds them.
        if _PLAN_RANK.get(p["plan"] or "free", 0) > _PLAN_RANK.get(org["plan"], 0):
            org["plan"] = p["plan"] or "free"
        if p["stripe_customer_id"] and not org["stripe_customer_id"]:
            org["stripe_customer_id"] = p["stripe_customer_id"]
            org["stripe_subscription_id"] = p["stripe_subscription_id"]
            org["subscription_status"] = p["subscription_status"]

    for owner, org in orgs.items():
        seats = {
            m["user_id"] for p in org["projects"] for m in (by_project.get(p["id"]) or [])
        } | {owner}
        # Solo owner with a single workspace = a personal account; anything larger is a team, and
        # must be a company or its existing workspaces/seats would sit over the personal cap.
        kind = "personal" if (len(org["projects"]) == 1 and len(seats) == 1) else "company"
        conn.execute(
            text(
                """
                INSERT INTO organizations
                    (id, name, slug, kind, plan, stripe_customer_id, stripe_subscription_id,
                     subscription_status)
                VALUES (:id, :name, :slug, :kind, :plan, :cus, :sub, :status)
                """
            ),
            {
                "id": org["id"], "name": org["name"], "slug": org["slug"], "kind": kind,
                "plan": org["plan"], "cus": org["stripe_customer_id"],
                "sub": org["stripe_subscription_id"], "status": org["subscription_status"],
            },
        )
        for p in org["projects"]:
            conn.execute(
                text("UPDATE projects SET organization_id = :org WHERE id = :pid"),
                {"org": org["id"], "pid": p["id"]},
            )

        # Strongest role a user held on any of the org's projects; the owner is always OWNER.
        roles: dict[str, str] = {owner: "OWNER"}
        for p in org["projects"]:
            for m in by_project.get(p["id"]) or []:
                cur = roles.get(m["user_id"])
                if cur is None or _ROLE_RANK.get(m["role"], 0) > _ROLE_RANK.get(cur, 0):
                    roles[m["user_id"]] = m["role"]
        roles[owner] = "OWNER"
        for user_id, role in roles.items():
            conn.execute(
                text(
                    """
                    INSERT INTO organization_memberships (id, organization_id, user_id, role)
                    VALUES (:id, :org, :uid, :role)
                    ON CONFLICT (organization_id, user_id) DO NOTHING
                    """
                ),
                {"id": str(uuid4()), "org": org["id"], "uid": user_id, "role": role},
            )

    # Pending invites follow their project into its new org; org-less ones are dead anyway.
    conn.execute(
        text(
            """
            UPDATE invitations SET organization_id = (
                SELECT p.organization_id FROM projects p WHERE p.id = invitations.project_id
            )
            WHERE organization_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_invitations_organization_id")
    op.execute("ALTER TABLE invitations DROP COLUMN IF EXISTS organization_id")
    op.execute("DROP INDEX IF EXISTS ix_projects_organization_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS organization_id")
    op.execute("DROP TABLE IF EXISTS organization_memberships")
    op.execute("DROP TABLE IF EXISTS organizations")
