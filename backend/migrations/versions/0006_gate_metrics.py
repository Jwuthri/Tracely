"""gate metrics for delta-vs-baseline soft gates: latency_ms, total_tokens, warnings

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gate_runs", sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"))
    op.add_column("gate_runs", sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("gate_runs", sa.Column("warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("gate_runs", "warnings")
    op.drop_column("gate_runs", "total_tokens")
    op.drop_column("gate_runs", "latency_ms")
