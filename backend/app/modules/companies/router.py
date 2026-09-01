"""Company profile, departments and locations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuditAction, CompanySize, CompanyStatus
from app.core.exceptions import BusinessRuleError, DuplicateResource, ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.company import Company, CompanyLocation, Department
from app.models.job import Job
from app.models.user import User
from app.schemas.common import DeleteResponse, ORMModel
from app.services.audit import AuditService, diff
from app.utils.text import slugify

router = APIRouter(prefix="/companies", tags=["Companies"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class CompanyOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    legal_name: str | None = None
    description: str | None = None
    logo_url: str | None = None
    website: str | None = None
    industry: str | None = None
    size: CompanySize | None = None
    founded_year: int | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    headquarters: str | None = None
    status: CompanyStatus
    subscription_plan: str
    settings: dict = Field(default_factory=dict)
    social_links: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    logo_url: str | None = Field(default=None, max_length=512)
    website: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    size: CompanySize | None = None
    founded_year: int | None = Field(default=None, ge=1800, le=2100)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    headquarters: str | None = Field(default=None, max_length=255)
    social_links: dict | None = None


class SettingsUpdate(BaseModel):
    """Tenant configuration.

    Only the keys listed here are accepted, so a client cannot write arbitrary data into
    the settings blob.
    """

    interview_reminder_offsets_minutes: list[int] | None = Field(
        default=None, max_length=5, description="e.g. [1440, 60] for 24h and 1h before"
    )
    default_offer_validity_days: int | None = Field(default=None, ge=1, le=90)
    auto_score_on_apply: bool | None = None
    require_offer_approval: bool | None = None
    candidate_data_retention_days: int | None = Field(default=None, ge=30, le=3650)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    head_user_id: uuid.UUID | None = None


class DepartmentOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    head_user_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    timezone: str = Field(default="UTC", max_length=64)
    is_headquarters: bool = False


class LocationOut(ORMModel):
    id: uuid.UUID
    name: str
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    timezone: str
    is_headquarters: bool
    is_active: bool


@router.get(
    "/me",
    response_model=SuccessResponse[CompanyOut],
    summary="Get your company",
    dependencies=[Depends(require_permission(Perm.COMPANY_READ))],
)
async def get_my_company(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[CompanyOut]:
    company = await session.get(Company, company_id)
    if company is None:
        raise ResourceNotFound("Company", company_id)
    return SuccessResponse(data=CompanyOut.model_validate(company))


@router.patch(
    "/me",
    response_model=SuccessResponse[CompanyOut],
    summary="Update your company profile",
    dependencies=[Depends(require_permission(Perm.COMPANY_UPDATE))],
)
async def update_my_company(
    payload: CompanyUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CompanyOut]:
    company = await session.get(Company, company_id)
    if company is None:
        raise ResourceNotFound("Company", company_id)

    changes = payload.model_dump(exclude_unset=True)
    before = {k: getattr(company, k, None) for k in changes}
    for field, value in changes.items():
        if value is not None:
            setattr(company, field, value)
    if changes.get("name"):
        # The slug is a public identifier; keep it unique across the platform.
        candidate_slug = slugify(changes["name"])
        clash = await session.scalar(
            select(Company).where(Company.slug == candidate_slug, Company.id != company.id)
        )
        if clash is None:
            company.slug = candidate_slug

    await session.flush()
    await AuditService(session).record_for(
        principal,
        action=AuditAction.UPDATE,
        entity_type="Company",
        entity_id=company.id,
        summary=f"Updated company profile for {company.name}",
        changes=diff(before, {k: getattr(company, k, None) for k in before}),
    )
    return SuccessResponse(data=CompanyOut.model_validate(company), message="Company updated")


@router.put(
    "/me/settings",
    response_model=SuccessResponse[dict],
    summary="Update company settings",
    description="Hiring defaults: reminder offsets, offer validity, retention and more.",
    dependencies=[Depends(require_permission(Perm.COMPANY_UPDATE))],
)
async def update_settings(
    payload: SettingsUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[dict]:
    company = await session.get(Company, company_id)
    if company is None:
        raise ResourceNotFound("Company", company_id)

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    company.settings = {**(company.settings or {}), **updates}
    await session.flush()

    await AuditService(session).record_for(
        principal,
        action=AuditAction.UPDATE,
        entity_type="Company",
        entity_id=company.id,
        summary="Updated company hiring settings",
        changes={"settings": {"to": updates}},
    )
    return SuccessResponse(data=company.settings, message="Settings updated")


# ------------------------------------------------------------- departments
@router.get(
    "/me/departments",
    response_model=SuccessResponse[list[DepartmentOut]],
    summary="List departments",
    dependencies=[Depends(require_permission(Perm.COMPANY_READ))],
)
async def list_departments(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[DepartmentOut]]:
    rows = (
        (
            await session.execute(
                select(Department)
                .where(Department.company_id == company_id)
                .order_by(Department.name)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(data=[DepartmentOut.model_validate(d) for d in rows])


@router.post(
    "/me/departments",
    response_model=SuccessResponse[DepartmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a department",
    dependencies=[Depends(require_permission(Perm.DEPARTMENT_MANAGE))],
)
async def create_department(
    payload: DepartmentIn, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[DepartmentOut]:
    existing = await session.scalar(
        select(Department).where(
            Department.company_id == company_id, Department.name == payload.name.strip()
        )
    )
    if existing is not None:
        raise DuplicateResource(f"A department named '{payload.name}' already exists")

    department = Department(company_id=company_id, **payload.model_dump())
    session.add(department)
    await session.flush()
    return SuccessResponse(
        data=DepartmentOut.model_validate(department), message="Department created"
    )


@router.delete(
    "/me/departments/{department_id}",
    response_model=SuccessResponse[DeleteResponse],
    summary="Delete a department",
    dependencies=[Depends(require_permission(Perm.DEPARTMENT_MANAGE))],
)
async def delete_department(
    department_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[DeleteResponse]:
    department = await session.scalar(
        select(Department).where(
            Department.id == department_id, Department.company_id == company_id
        )
    )
    if department is None:
        raise ResourceNotFound("Department", department_id)

    in_use = await session.scalar(
        select(Job.id).where(Job.department_id == department_id, Job.deleted_at.is_(None)).limit(1)
    )
    if in_use is not None:
        raise BusinessRuleError(
            "This department still has jobs attached. Reassign them first, or "
            "deactivate the department instead of deleting it.",
            code="DEPARTMENT_IN_USE",
        )

    await session.delete(department)
    await session.flush()
    return SuccessResponse(
        data=DeleteResponse(id=department_id, message="Department deleted"),
        message="Department deleted",
    )


# ---------------------------------------------------------------- locations
@router.get(
    "/me/locations",
    response_model=SuccessResponse[list[LocationOut]],
    summary="List office locations",
    dependencies=[Depends(require_permission(Perm.COMPANY_READ))],
)
async def list_locations(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[LocationOut]]:
    rows = (
        (
            await session.execute(
                select(CompanyLocation)
                .where(CompanyLocation.company_id == company_id)
                .order_by(CompanyLocation.is_headquarters.desc(), CompanyLocation.name)
            )
        )
        .scalars()
        .all()
    )
    return SuccessResponse(data=[LocationOut.model_validate(loc) for loc in rows])


@router.post(
    "/me/locations",
    response_model=SuccessResponse[LocationOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add an office location",
    dependencies=[Depends(require_permission(Perm.DEPARTMENT_MANAGE))],
)
async def create_location(
    payload: LocationIn, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[LocationOut]:
    if payload.is_headquarters:
        # Exactly one headquarters.
        for existing in (
            (
                await session.execute(
                    select(CompanyLocation).where(
                        CompanyLocation.company_id == company_id,
                        CompanyLocation.is_headquarters.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        ):
            existing.is_headquarters = False

    location = CompanyLocation(company_id=company_id, **payload.model_dump())
    session.add(location)
    await session.flush()
    return SuccessResponse(
        data=LocationOut.model_validate(location), message="Location added"
    )


@router.get(
    "/me/team",
    response_model=SuccessResponse[list[dict]],
    summary="List the hiring team",
    description="Everyone in the company who can be assigned to jobs or interviews.",
    dependencies=[Depends(require_permission(Perm.USER_READ))],
)
async def list_team(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[dict]]:
    from sqlalchemy.orm import selectinload

    users = (
        (
            await session.execute(
                select(User)
                .where(User.company_id == company_id, User.deleted_at.is_(None))
                .options(selectinload(User.roles))
                .order_by(User.first_name)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return SuccessResponse(
        data=[
            {
                "id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "job_title": u.job_title,
                "avatar_url": u.avatar_url,
                "status": u.status.value,
                "roles": sorted(u.role_names),
                "department_id": str(u.department_id) if u.department_id else None,
            }
            for u in users
        ]
    )
