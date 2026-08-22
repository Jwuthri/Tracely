"""session revocation: a counter on the user that every session token carries

Sessions are stateless HS256 JWTs, so until now nothing could end one early — a password reset
took the account back but left any session an intruder already held alive for up to 7 days.

`users.token_version` is stamped into each token as `tv` and compared on every request. Bumping it
invalidates every token issued before the bump, which is exactly what "I'm taking this account
back" has to mean. Cheap: the user row is already loaded to check `is_active`.

Existing tokens have no `tv` claim and read as 0, which equals the column default — so deploying
this does NOT sign everyone out.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
