"""Startup reconciliation of the permission catalogue and built-in roles.

Runs on every boot and is idempotent. Adding a permission constant to
``app.core.permissions`` is therefore all that is needed to roll it out - the row and the
role grants appear automatically, and grants removed from the matrix are revoked.
Custom, company-defined roles are never touched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.permissions import ALL_PERMISSIONS, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.models.user import Permission, Role

logger = get_logger(__name__)


def _describe(code: str) -> str:
    resource, _, action = code.partition(":")
    return f"{action.replace(':', ' ').replace('_', ' ').title()} {resource.replace('_', ' ')}"


async def sync_permissions(session: AsyncSession) -> dict[str, Permission]:
    existing = {
        permission.code: permission
        for permission in (await session.execute(select(Permission))).scalars()
    }
    created = 0
    for code in sorted(ALL_PERMISSIONS):
        if code not in existing:
            permission = Permission(code=code, description=_describe(code))
            session.add(permission)
            existing[code] = permission
            created += 1
    if created:
        await session.flush()
        logger.info("permissions_synced", created=created, total=len(existing))
    return existing


async def sync_system_roles(session: AsyncSession) -> None:
    permissions = await sync_permissions(session)

    stmt = (
        select(Role)
        .where(Role.company_id.is_(None), Role.is_system.is_(True))
        .options(selectinload(Role.permissions))
    )
    existing = {role.name: role for role in (await session.execute(stmt)).unique().scalars()}

    for role_name, granted_codes in ROLE_PERMISSIONS.items():
        role = existing.get(role_name.value)
        if role is None:
            role = Role(
                name=role_name.value,
                description=ROLE_DESCRIPTIONS.get(role_name),
                is_system=True,
                company_id=None,
            )
            # Assign the collection before the row is persisted. Touching
            # ``role.permissions`` on a freshly flushed instance would trigger a lazy
            # load, which raises MissingGreenlet under the async session.
            role.permissions = []
            session.add(role)
            logger.info("system_role_created", role=role_name.value)
        else:
            role.description = ROLE_DESCRIPTIONS.get(role_name, role.description)

        current = {p.code for p in role.permissions}
        desired = set(granted_codes)

        for code in desired - current:
            if permission := permissions.get(code):
                role.permissions.append(permission)
        for permission in [p for p in role.permissions if p.code not in desired]:
            role.permissions.remove(permission)

    await session.flush()


async def bootstrap_database(session: AsyncSession) -> None:
    await sync_system_roles(session)


async def ensure_schema() -> None:
    """Create tables directly from the metadata.

    Alembic owns the schema in every real deployment. This exists for the SQLite
    zero-setup path (local dev and the test-suite), where running a migration chain
    against a throwaway file buys nothing.
    """
    from app.core.config import settings
    from app.db.session import engine
    from app.models import Base

    if not settings.is_sqlite:
        logger.info("schema_managed_by_alembic", url_scheme=settings.DATABASE_URL.split("://")[0])
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("schema_ensured", backend="sqlite")
