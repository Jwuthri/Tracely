"""agent_endpoints.session_path: read a session id the endpoint MINTS, instead of pushing ours.

Two opposite conventions. Most agent APIs accept a client-supplied session id — we send ours on
every turn and they key their state off it (`session_key`, unchanged). Others own the identity:
turn 1 carries no session, the response names one, and every later turn must echo that value.
Without this an endpoint of the second kind starts a fresh conversation per turn, and a 3-turn
scenario grades three disconnected greetings.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_endpoints ADD COLUMN IF NOT EXISTS session_path VARCHAR(200) DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_endpoints DROP COLUMN IF EXISTS session_path")
