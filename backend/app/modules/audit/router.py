"""Audit log access.

Read-only by design: no endpoint here (or anywhere) updates or deletes an audit row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuditAction
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CurrentUser, require_permission
from app.models.audit import AuditLog
from app.schemas.common import ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/audit-logs", tags=["Admin"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class AuditLogOut(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_email: str | None = None
    actor_roles: list = Field(default_factory=list)
    action: AuditAction
    entity_type: str
    entity_id: uuid.UUID | None = None
    summary: str
    changes: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime


@router.get(
    "",
    response_model=SuccessResponse[Page[AuditLogOut]],
    summary="Search the audit log",
    description=(
        "Company admins see their own company's log; platform admins see everything. "
        "Entries are append-only - nothing in the API can modify or remove them."
    ),
    dependencies=[Depends(require_permission(Perm.AUDIT_READ))],
)
async def list_audit_logs(
    principal: CurrentUser,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    action: Annotated[list[AuditAction] | None, Query()] = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    q: Annotated[str | None, Query(description="Search the summary text")] = None,
    company_id: Annotated[
        uuid.UUID | None, Query(description="Platform admins only")
    ] = None,
) -> SuccessResponse[Page[AuditLogOut]]:
    stmt = select(AuditLog)

    # Tenant scoping: a company admin can never widen this.
    if principal.is_super_admin:
        if company_id:
            stmt = stmt.where(AuditLog.company_id == company_id)
    else:
        stmt = stmt.where(AuditLog.company_id == principal.company_id)

    if action:
        stmt = stmt.where(AuditLog.action.in_(action))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(since, datetime.min.time()))
    if until:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(until, datetime.max.time()))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(AuditLog.summary.ilike(pattern), AuditLog.actor_email.ilike(pattern))
        )

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(AuditLog.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [AuditLogOut.model_validate(r) for r in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=SuccessResponse[list[AuditLogOut]],
    summary="Audit history for one entity",
    dependencies=[Depends(require_permission(Perm.AUDIT_READ))],
)
async def entity_history(
    entity_type: str,
    entity_id: uuid.UUID,
    principal: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SuccessResponse[list[AuditLogOut]]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if not principal.is_super_admin:
        stmt = stmt.where(AuditLog.company_id == principal.company_id)

    rows = (await session.execute(stmt)).scalars().all()
    return SuccessResponse(data=[AuditLogOut.model_validate(r) for r in rows])


@router.get(
    "/actions",
    response_model=SuccessResponse[list[str]],
    summary="Available audit action types",
    dependencies=[Depends(require_permission(Perm.AUDIT_READ))],
)
async def list_actions() -> SuccessResponse[list[str]]:
    return SuccessResponse(data=[a.value for a in AuditAction])
