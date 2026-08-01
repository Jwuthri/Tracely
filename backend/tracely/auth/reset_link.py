"""Print a password-reset link for a local account, from the server.

    python -m tracely.auth.reset_link someone@example.com

The escape hatch for self-hosted installs: `POST /auth/forgot-password` can only *email* the link,
so with `RESEND_API_KEY` unset there is otherwise no way back into a locked-out account. Running
this requires shell access to the backend, which is a strictly stronger credential than the
account being recovered — so printing the link here grants nothing new.

It mints the same single-use, 1-hour grant the HTTP endpoint does; it does NOT set a password and
never asks for one. The operator opens the link and chooses the password themselves.
"""

from __future__ import annotations

import asyncio
import sys

from tracely.auth.password_reset import create_reset
from tracely.infrastructure.db.engine import AsyncSessionLocal
from tracely.infrastructure.mailer import reset_url


async def _main(email: str) -> int:
    async with AsyncSessionLocal() as session:
        grant = await create_reset(session, email)
    if grant is None:
        print(f"no local account for {email!r}", file=sys.stderr)
        return 1
    raw, user = grant
    print(f"reset link for {user.email} (expires in 1 hour, single use):\n\n{reset_url(raw)}\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m tracely.auth.reset_link <email>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(sys.argv[1])))
