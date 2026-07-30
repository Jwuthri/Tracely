"""project openrouter key: a workspace's own OpenRouter key for its LLM eval spend.

Nullable, Fernet-encrypted at rest (see infrastructure/llm/provider.py). NULL keeps today's
behavior (the server-wide OPENROUTER_API_KEY); once set, every LLM call scoped to this project
(judge, failure intelligence, meta-analysis, rolling summary) uses it instead.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS, not a plain add_column: an additive nullable column is safe to apply ahead of
    # the code that uses it (migrate-then-deploy), so this may already have been added by hand to
    # avoid a window where the new code queries a column that isn't there yet. Idempotent means
    # that head start never turns into a failed deploy here.
    op.execute(
        "ALTER TABLE projects "
        "ADD COLUMN IF NOT EXISTS openrouter_api_key_encrypted VARCHAR(512)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS openrouter_api_key_encrypted")
