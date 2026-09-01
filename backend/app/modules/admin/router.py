"""Platform administration. Super-admin only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import AuditAction, CompanySize, CompanyStatus, RoleName, UserStatus
from app.core.exceptions import DuplicateResource, ResourceNotFound
from app.core.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.core.responses import Page, SuccessResponse
from app.core.security import generate_url_token, hash_password
from app.db.session import get_db
from app.dependencies.auth import SuperAdmin
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.job import Job
from app.models.user import Role, User
from app.schemas.common import ORMModel, PaginationParams, pagination
from app.services.audit import AuditService
from app.utils.text import slugify

router = APIRouter(prefix="/admin", tags=["Admin"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr
    admin_first_name: str = Field(min_length=1, max_length=100)
    admin_last_name: str = Field(min_length=1, max_length=100)
    industry: str | None = Field(default=None, max_length=120)
    size: CompanySize | None = None
    website: str | None = Field(default=None, max_length=255)
    subscription_plan: str = Field(default="trial", max_length=50)


class CompanyAdminOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    industry: str | None = None
    size: CompanySize | None = None
    status: CompanyStatus
    subscription_plan: str
    created_at: datetime
    user_count: int = 0
    job_count: int = 0
    application_count: int = 0


class CompanyCreatedOut(BaseModel):
    company: CompanyAdminOut
    admin_user_id: uuid.UUID
    admin_email: EmailStr
    setup_link: str
    invitation_email_status: str
    message: str


class CompanyStatusChange(BaseModel):
    status: CompanyStatus
    reason: str | None = Field(default=None, max_length=500)


class PlatformStatsOut(BaseModel):
    companies: dict[str, int]
    users: dict[str, int]
    jobs: dict[str, int]
    applications: dict[str, int]
    candidates: int
    providers: dict[str, dict]


@router.get(
    "/stats",
    response_model=SuccessResponse[PlatformStatsOut],
    summary="Platform-wide statistics",
)
async def platform_stats(
    _admin: SuperAdmin, session: DbSession
) -> SuccessResponse[PlatformStatsOut]:
    async def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return (await session.execute(stmt)).scalar_one()

    week_ago = datetime.now(UTC) - timedelta(days=7)

    from app.providers.ai.factory import get_ai_provider
    from app.providers.calendar import get_calendar_provider
    from app.providers.email import get_email_provider
    from app.providers.storage import get_storage

    ai, storage, email, calendar = (
        get_ai_provider(),
        get_storage(),
        get_email_provider(),
        get_calendar_provider(),
    )

    return SuccessResponse(
        data=PlatformStatsOut(
            companies={
                "total": await count(Company, Company.deleted_at.is_(None)),
                "active": await count(
                    Company,
                    Company.deleted_at.is_(None),
                    Company.status == CompanyStatus.ACTIVE,
                ),
                "trial": await count(
                    Company,
                    Company.deleted_at.is_(None),
                    Company.status == CompanyStatus.TRIAL,
                ),
            },
            users={
                "total": await count(User, User.deleted_at.is_(None)),
                "active": await count(
                    User, User.deleted_at.is_(None), User.status == UserStatus.ACTIVE
                ),
                "new_this_week": await count(User, User.created_at >= week_ago),
            },
            jobs={
                "total": await count(Job, Job.deleted_at.is_(None)),
                "published": await count(
                    Job, Job.deleted_at.is_(None), Job.status == "PUBLISHED"
                ),
            },
            applications={
                "total": await count(Application),
                "this_week": await count(Application, Application.created_at >= week_ago),
            },
            candidates=await count(Candidate, Candidate.deleted_at.is_(None)),
            providers={
                "ai": {"name": ai.name, "real_model": ai.is_real_model},
                "storage": {"name": storage.name, "durable": storage.is_durable},
                "email": {"name": email.name, "transmits": email.transmits},
                "calendar": {
                    "name": calendar.name,
                    "delivers_invitations": calendar.delivers_invitations,
                },
            },
        )
    )


@router.get(
    "/companies",
    response_model=SuccessResponse[Page[CompanyAdminOut]],
    summary="List all companies",
)
async def list_companies(
    _admin: SuperAdmin,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query()] = None,
    company_status: Annotated[CompanyStatus | None, Query(alias="status")] = None,
) -> SuccessResponse[Page[CompanyAdminOut]]:
    stmt = select(Company).where(Company.deleted_at.is_(None))
    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q.strip()}%"))
    if company_status:
        stmt = stmt.where(Company.status == company_status)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Company.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .all()
    )

    items: list[CompanyAdminOut] = []
    for company in rows:
        payload = CompanyAdminOut.model_validate(company)
        payload.user_count = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.company_id == company.id, User.deleted_at.is_(None))
            )
        ).scalar_one()
        payload.job_count = (
            await session.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.company_id == company.id, Job.deleted_at.is_(None))
            )
        ).scalar_one()
        payload.application_count = (
            await session.execute(
                select(func.count())
                .select_from(Application)
                .where(Application.company_id == company.id)
            )
        ).scalar_one()
        items.append(payload)

    return SuccessResponse(
        data=Page.build(
            items, page=page_params.page, page_size=page_params.page_size, total=total
        )
    )


@router.post(
    "/companies",
    response_model=SuccessResponse[CompanyCreatedOut],
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a new company",
    description=(
        "Creates the tenant, its first company admin, the default ATS weight profile and "
        "the company's copy of every email template."
    ),
)
async def create_company(
    payload: CompanyCreate, admin: SuperAdmin, session: DbSession
) -> SuccessResponse[CompanyCreatedOut]:
    email = payload.admin_email.strip().lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise DuplicateResource("An account with this email already exists")

    slug = slugify(payload.name)
    if await session.scalar(select(Company).where(Company.slug == slug)):
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    company = Company(
        name=payload.name.strip(),
        slug=slug,
        industry=payload.industry,
        size=payload.size,
        website=payload.website,
        subscription_plan=payload.subscription_plan,
        status=CompanyStatus.TRIAL,
        contact_email=email,
    )
    session.add(company)
    await session.flush()

    role = await session.scalar(
        select(Role).where(
            Role.name == RoleName.COMPANY_ADMIN.value, Role.company_id.is_(None)
        )
    )
    if role is None:
        raise ResourceNotFound("Role", RoleName.COMPANY_ADMIN.value)

    user = User(
        email=email,
        hashed_password=hash_password(generate_url_token()),
        first_name=payload.admin_first_name.strip(),
        last_name=payload.admin_last_name.strip(),
        company_id=company.id,
        status=UserStatus.PENDING_VERIFICATION,
    )
    user.roles.append(role)
    session.add(user)
    await session.flush()

    # Give the new tenant everything it needs to work immediately.
    from app.modules.ats.service import AtsService
    from app.modules.emails.service import EmailService

    await AtsService(session, company.id).ensure_default_profile()
    await EmailService(session, company.id).ensure_default_templates()

    from app.modules.auth.service import PURPOSE_PASSWORD_RESET, AuthService

    raw_token = await AuthService(session).issue_verification_token(
        user, PURPOSE_PASSWORD_RESET
    )
    await session.flush()
    setup_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}&setup=1"

    from app.modules.auth.router import _send_account_email

    email_status = await _send_account_email(
        to=user.email,
        subject=f"Your HireHQ workspace for {company.name} is ready",
        heading="Set up your HireHQ account",
        body=(
            f"A HireHQ workspace has been created for {company.name}. Set your password "
            "to sign in and start hiring."
        ),
        link=setup_link,
        cta="Set your password",
    )

    await AuditService(session).record_for(
        admin,
        action=AuditAction.CREATE,
        entity_type="Company",
        entity_id=company.id,
        summary=f"Created company '{company.name}' with admin {email}",
    )

    payload_out = CompanyAdminOut.model_validate(company)
    return SuccessResponse(
        data=CompanyCreatedOut(
            company=payload_out,
            admin_user_id=user.id,
            admin_email=user.email,
            setup_link=setup_link,
            invitation_email_status=email_status.value,
            message=(
                "Company created and the admin was emailed a setup link."
                if email_status.value == "SENT"
                else (
                    "Company created. No email provider is configured, so share the "
                    "setup link with the admin directly."
                )
            ),
        ),
        message="Company created",
    )


@router.post(
    "/companies/{company_id}/status",
    response_model=SuccessResponse[CompanyAdminOut],
    summary="Change a company's status",
    description="Suspending a company signs out every one of its users immediately.",
)
async def change_company_status(
    company_id: uuid.UUID,
    payload: CompanyStatusChange,
    admin: SuperAdmin,
    session: DbSession,
) -> SuccessResponse[CompanyAdminOut]:
    company = await session.get(Company, company_id)
    if company is None:
        raise ResourceNotFound("Company", company_id)

    previous = company.status
    company.status = payload.status
    await session.flush()

    if payload.status == CompanyStatus.SUSPENDED:
        from app.modules.auth.service import AuthService

        auth = AuthService(session)
        user_ids = (
            (
                await session.execute(
                    select(User.id).where(
                        User.company_id == company_id, User.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in user_ids:
            await auth.revoke_all_sessions(user_id, reason="company_suspended")

    await AuditService(session).record_for(
        admin,
        action=AuditAction.STATUS_CHANGE,
        entity_type="Company",
        entity_id=company.id,
        summary=f"Company '{company.name}' moved from {previous.value} to {payload.status.value}",
        meta={"reason": payload.reason},
    )
    return SuccessResponse(
        data=CompanyAdminOut.model_validate(company),
        message=f"Company is now {payload.status.value.lower()}",
    )


@router.get(
    "/permissions",
    response_model=SuccessResponse[dict],
    summary="The permission catalogue and role matrix",
)
async def permission_matrix(_admin: SuperAdmin) -> SuccessResponse[dict]:
    return SuccessResponse(
        data={
            "permissions": sorted(ALL_PERMISSIONS),
            "roles": {
                role.value: sorted(permissions)
                for role, permissions in ROLE_PERMISSIONS.items()
            },
        }
    )


@router.get(
    "/users",
    response_model=SuccessResponse[Page[dict]],
    summary="Search users across every company",
)
async def list_all_users(
    _admin: SuperAdmin,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query()] = None,
    company_id: uuid.UUID | None = None,
) -> SuccessResponse[Page[dict]]:
    from sqlalchemy import or_

    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .options(selectinload(User.roles), selectinload(User.company))
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.email.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )
    if company_id:
        stmt = stmt.where(User.company_id == company_id)

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(User.created_at.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=Page.build(
            [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "full_name": u.full_name,
                    "status": u.status.value,
                    "roles": sorted(u.role_names),
                    "company": u.company.name if u.company else None,
                    "company_id": str(u.company_id) if u.company_id else None,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                    "created_at": u.created_at.isoformat(),
                }
                for u in rows
            ],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )
