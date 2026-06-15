"""advisory evaluator flag: backfill config.advisory on the subjective answer-quality judge

The roll-up-verdict policy (threads dot / trace badge / session / trends) now excludes "advisory"
evaluators' FAILs via the per-evaluator `config.advisory` flag, replacing the hardcoded
`name != 'tracely.run.quality'` magic string in the read layer. New installs get the flag from the
seed catalog; this backfills existing installs' `tracely.run.quality` evaluator so its behavior is
unchanged (its FAILs stay advisory).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE evaluators
        SET config = (COALESCE(config, '{}')::jsonb || '{"advisory": true}'::jsonb)::json
        WHERE score_name = 'tracely.run.quality'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE evaluators
        SET config = (config::jsonb - 'advisory')::json
        WHERE score_name = 'tracely.run.quality'
        """
    )
