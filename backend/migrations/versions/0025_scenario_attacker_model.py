"""scenarios.attacker_model: per-scenario model for the adversarial attacker.

The server-wide `attacker_model` setting is one model for every adversarial run. A red-team
suite wants to pin the attacker per scenario — probe this agent with a jailbreak-happy model,
that one with a stricter one. Blank keeps the server default. SCRIPTED scenarios ignore it.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS attacker_model VARCHAR(120) DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS attacker_model")
