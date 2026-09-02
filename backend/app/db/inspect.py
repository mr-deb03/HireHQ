"""Report what is actually in a database, before deciding what to do to it.

    python -m app.db.inspect

Reads ``DATABASE_URL`` from the environment (or ``.env``) and prints the migration
revision, the tables that exist and how many rows they hold. Read-only: it issues nothing
but SELECTs, and it never prints credentials.

This exists because a failed migration leaves a database in a state that is easy to
misread. "relation already exists" while Alembic reports the revision as empty means the
schema was created but never stamped - and the right recovery depends on whether those
tables hold real data or are the wreckage of a run that failed halfway.
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

#: Tables worth counting individually - enough to tell a seeded database from an empty one.
INTERESTING = ("users", "companies", "jobs", "candidates", "applications")


def describe_target(url: str) -> str:
    """Host and database name only. Never the user, never the password."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    database = (parts.path or "").lstrip("/") or "?"
    return f"{host}/{database}"


async def main() -> int:
    url = settings.DATABASE_URL
    print(f"\n  target : {describe_target(url)}")
    print(f"  driver : {url.split('://')[0]}\n")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            tables = list(
                await conn.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name"
                    )
                )
            )
            print(f"  tables in public schema : {len(tables)}")

            if "alembic_version" in tables:
                revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                print(f"  alembic revision        : {revision or '(row missing)'}")
            else:
                print("  alembic revision        : (no alembic_version table)")

            if not tables:
                print("\n  The schema is empty. `alembic upgrade head` will build it.\n")
                return 0

            # The names matter when the count is wrong: which tables survived says whether
            # this is a clean schema, a partial migration, or something else entirely.
            print("\n  present:")
            for i in range(0, len(tables), 4):
                print("    " + "  ".join(f"{n:<26}" for n in tables[i : i + 4]).rstrip())

            print()
            total = 0
            for name in INTERESTING:
                if name not in tables:
                    print(f"    {name:<14} (table not present)")
                    continue
                count = await conn.scalar(text(f'SELECT count(*) FROM "{name}"'))  # noqa: S608
                total += count or 0
                print(f"    {name:<14} {count:>8} rows")

            print()
            if total == 0:
                print("  Every table checked is empty - this schema holds no data.")
            else:
                print(f"  {total} rows across those tables. This database HAS DATA.")
                # Who those accounts belong to decides whether the data is worth keeping.
                # Emails only - never the password hashes or tokens sitting beside them.
                if "users" in tables:
                    accounts = list(
                        await conn.scalars(
                            text("SELECT email FROM users ORDER BY created_at LIMIT 20")
                        )
                    )
                    if accounts:
                        print("\n  accounts present:")
                        for email in accounts:
                            print(f"    {email}")

            expected = 57
            if len(tables) not in (0, expected, expected + 1):
                print(
                    f"\n  WARNING: {len(tables)} tables, but a complete schema has {expected}"
                    " (plus alembic_version). This schema is incomplete - most likely a"
                    " migration that failed partway and was not rolled back."
                )
            print()
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
