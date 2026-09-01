"""Employee referrals and internal job applications."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import AuditAction, JobStatus, ReferralStatus
from app.core.exceptions import DuplicateResource, ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.job import Job
from app.models.talent import Referral
from app.modules.jobs.schemas import JobSummary
from app.schemas.common import ORMModel, PaginationParams, pagination
from app.services.audit import AuditService

router = APIRouter(prefix="/referrals", tags=["Referrals"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class ReferralCreate(BaseModel):
    referred_name: str = Field(min_length=1, max_length=200)
    referred_email: EmailStr
    referred_phone: str | None = Field(default=None, max_length=32)
    job_id: uuid.UUID | None = None
    relationship_to_referrer: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=5000)


class ReferralOut(ORMModel):
    id: uuid.UUID
    referrer_id: uuid.UUID
    job_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    referred_name: str
    referred_email: EmailStr
    referred_phone: str | None = None
    relationship_to_referrer: str | None = None
    note: str | None = None
    status: ReferralStatus
    status_updated_at: datetime | None = None
    bonus_amount: float | None = None
    bonus_paid_at: datetime | None = None
    created_at: datetime
    job_title: str | None = None


class ReferralStatsOut(BaseModel):
    total_referrals: int
    by_status: dict[str, int]
    hired: int
    conversion_pct: float
    top_referrers: list[dict]


@router.post(
    "",
    response_model=SuccessResponse[ReferralOut],
    status_code=status.HTTP_201_CREATED,
    summary="Refer a candidate",
    dependencies=[Depends(require_permission(Perm.REFERRAL_CREATE))],
)
async def create_referral(
    payload: ReferralCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[ReferralOut]:
    email = payload.referred_email.strip().lower()

    existing = await session.scalar(
        select(Referral).where(
            Referral.company_id == company_id,
            Referral.referrer_id == principal.id,
            Referral.referred_email == email,
            Referral.job_id == payload.job_id,
        )
    )
    if existing is not None:
        raise DuplicateResource(
            "You have already referred this person for this role",
            details={"referral_id": str(existing.id)},
        )

    if payload.job_id:
        job = await session.scalar(
            select(Job).where(
                Job.id == payload.job_id,
                Job.company_id == company_id,
                Job.deleted_at.is_(None),
            )
        )
        if job is None:
            raise ResourceNotFound("Job", payload.job_id)

    referral = Referral(
        company_id=company_id,
        referrer_id=principal.id,
        job_id=payload.job_id,
        referred_name=payload.referred_name.strip(),
        referred_email=email,
        referred_phone=payload.referred_phone,
        relationship_to_referrer=payload.relationship_to_referrer,
        note=payload.note,
        status=ReferralStatus.REFERRED,
    )
    session.add(referral)
    await session.flush()

    await AuditService(session).record_for(
        principal,
        action=AuditAction.CREATE,
        entity_type="Referral",
        entity_id=referral.id,
        summary=f"{principal.full_name} referred {payload.referred_name}",
    )

    return SuccessResponse(
        data=ReferralOut.model_validate(referral),
        message=(
            "Referral recorded. Ask them to apply using their email so we can link the "
            "application to your referral."
        ),
    )


@router.get(
    "/mine",
    response_model=SuccessResponse[list[ReferralOut]],
    summary="Track your referrals",
    dependencies=[Depends(require_permission(Perm.REFERRAL_READ_OWN, Perm.REFERRAL_READ))],
)
async def my_referrals(
    principal: CurrentUser, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[ReferralOut]]:
    rows = (
        (
            await session.execute(
                select(Referral)
                .where(
                    Referral.company_id == company_id,
                    Referral.referrer_id == principal.id,
                )
                .order_by(Referral.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(data=[ReferralOut.model_validate(r) for r in rows])


@router.get(
    "",
    response_model=SuccessResponse[Page[ReferralOut]],
    summary="List all referrals",
    dependencies=[Depends(require_permission(Perm.REFERRAL_READ))],
)
async def list_referrals(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    referral_status: Annotated[list[ReferralStatus] | None, Query(alias="status")] = None,
    job_id: uuid.UUID | None = None,
) -> SuccessResponse[Page[ReferralOut]]:
    stmt = select(Referral).where(Referral.company_id == company_id)
    if referral_status:
        stmt = stmt.where(Referral.status.in_(referral_status))
    if job_id:
        stmt = stmt.where(Referral.job_id == job_id)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Referral.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [ReferralOut.model_validate(r) for r in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/stats",
    response_model=SuccessResponse[ReferralStatsOut],
    summary="Referral analytics",
    dependencies=[Depends(require_permission(Perm.REFERRAL_READ))],
)
async def referral_stats(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ReferralStatsOut]:
    from app.models.user import User

    rows = (
        await session.execute(
            select(Referral.status, func.count())
            .where(Referral.company_id == company_id)
            .group_by(Referral.status)
        )
    ).all()
    by_status = {row[0].value: row[1] for row in rows}
    total = sum(by_status.values())
    hired = by_status.get(ReferralStatus.HIRED.value, 0)

    top = (
        await session.execute(
            select(
                User.id,
                User.first_name,
                User.last_name,
                func.count(Referral.id).label("referrals"),
                func.sum(
                    case((Referral.status == ReferralStatus.HIRED, 1), else_=0)
                ).label("hired"),
            )
            .join(Referral, Referral.referrer_id == User.id)
            .where(Referral.company_id == company_id)
            .group_by(User.id, User.first_name, User.last_name)
            .order_by(func.count(Referral.id).desc())
            .limit(10)
        )
    ).all()

    return SuccessResponse(
        data=ReferralStatsOut(
            total_referrals=total,
            by_status=by_status,
            hired=hired,
            conversion_pct=round(hired / total * 100, 2) if total else 0.0,
            top_referrers=[
                {
                    "user_id": str(row[0]),
                    "name": f"{row[1]} {row[2]}",
                    "referrals": int(row[3] or 0),
                    "hired": int(row[4] or 0),
                }
                for row in top
            ],
        )
    )


# ------------------------------------------------------------ internal jobs
internal_router = APIRouter(prefix="/internal-jobs", tags=["Referrals"])


@internal_router.get(
    "",
    response_model=SuccessResponse[list[JobSummary]],
    summary="Internal careers listing",
    description="Published roles open to employees, including internal-only openings.",
    dependencies=[Depends(require_permission(Perm.JOB_READ, Perm.REFERRAL_CREATE))],
)
async def internal_jobs(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[JobSummary]]:
    rows = (
        (
            await session.execute(
                select(Job)
                .where(
                    Job.company_id == company_id,
                    Job.status == JobStatus.PUBLISHED,
                    Job.deleted_at.is_(None),
                )
                .options(selectinload(Job.skills))
                .order_by(Job.published_at.desc().nullslast())
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(data=[JobSummary.model_validate(j) for j in rows])
