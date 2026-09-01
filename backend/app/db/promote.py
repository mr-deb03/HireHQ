"""Grant a role to an existing user.

Deploying HireHQ leaves you with no way in: self-registration always produces a CANDIDATE
(by design - a public signup form must never be able to mint an administrator), and the
demo seed is unsafe on a real deployment because its passwords are published in this
repository. So the first administrator is promoted deliberately, once, with this script.

    python -m app.db.promote you@example.com
    python -m app.db.promote you@example.com --role COMPANY_ADMIN

It is idempotent: running it twice is harmless.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.enums import RoleName
from app.db.session import session_scope
from app.models.user import Role, User


async def promote(email: str, role_name: str) -> int:
    normalised = email.strip().lower()

    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == normalised))
        if user is None:
            print(f"No account found for {normalised!r}.")
            print("Register through the website first, then run this again.")
            return 1

        # System roles are the ones with no company attached; a company's own custom
        # roles share names but belong to that tenant.
        role = await session.scalar(
            select(Role).where(Role.name == role_name, Role.company_id.is_(None))
        )
        if role is None:
            print(f"Role {role_name!r} does not exist in this database.")
            print("Have the migrations been run? See DEPLOY-SIMPLE.md part 5.")
            return 1

        held = {r.name for r in user.roles}
        if role_name in held:
            print(f"{user.email} already has {role_name}. Nothing to do.")
            return 0

        user.roles.append(role)
        # session_scope commits on a clean exit.

    print(f"Done. {normalised} is now {role_name}.")
    print("Sign out and sign back in - your current session still has the old access.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant a role to an existing HireHQ user.",
        epilog="Example:  python -m app.db.promote you@example.com",
    )
    parser.add_argument("email", help="Email address of an account that already exists")
    parser.add_argument(
        "--role",
        default=RoleName.SUPER_ADMIN.value,
        choices=[r.value for r in RoleName],
        help="Role to grant (default: SUPER_ADMIN)",
    )
    args = parser.parse_args()
    return asyncio.run(promote(args.email, args.role))


if __name__ == "__main__":
    sys.exit(main())
