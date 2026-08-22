"""drop evaluation_cases.tool_args_mode — dead config that would be wrong if enforced

The column has said `"exact"` on every row since 0002 and nothing has ever read it. The obvious
reading of the backlog item ("enforce it, so wrong-arg traces become discriminating cases") is
backwards for how Tracely builds a case.

In dataset-style evals the reference trajectory is the GOLDEN run, so "tool args must match
exactly" means "call the tool correctly". Tracely's reference is a PRODUCTION FAILURE. Matching its
args exactly would assert the bug: an agent fixed to pass the right date now differs from the
recorded wrong one and fails the case for ever — a permanently red gate on correct code, which is
worse than the gap it was meant to close.

The gap itself is already handled honestly. A wrong-arg trace promotes to a case the source trace
PASSES, so `_record_fail_to_pass` leaves it `fail_to_pass_validated=False` / status DRAFT and it
never gates anything. "We can't discriminate this one" is the truthful outcome.

Arg-level discrimination needs a human-authored expectation ("must call search_flights with
departure=2026-06-02"), not a copy of the failing run's arguments — a different feature, on the
assertions blob, not this column.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("evaluation_cases", "tool_args_mode")


def downgrade() -> None:
    op.add_column(
        "evaluation_cases",
        sa.Column("tool_args_mode", sa.String(16), nullable=False, server_default="exact"),
    )
