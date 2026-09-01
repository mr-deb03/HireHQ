"""Company user management: invite staff, assign roles, activate and deactivate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import AuditAction, RoleName, UserStatus
from app.core.exceptions import (
    BusinessRuleError,
    DuplicateResource,
    ResourceNotFound,
    ValidationError,
)
from app.core.permissions import ROLE_DESCRIPTIONS, Perm
from app.core.responses import Page, SuccessResponse
from app.core.security import generate_url_token, hash_password
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.user import Role, User
from app.modules.auth.schemas import UserProfile
from app.modules.auth.service import PURPOSE_PASSWORD_RESET, AuthService
from app.schemas.common import PaginationParams, pagination
from app.services.audit import AuditService

router = APIRouter(prefix="/users", tags=["Users"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

#: Roles a company admin may grant. SUPER_ADMIN is platform-level and deliberately absent
#: - a tenant admin must never be able to escalate to platform ownership.
GRANTABLE_ROLES = frozenset(
    {
        RoleName.COMPANY_ADMIN,
        RoleName.RECRUITER,
        RoleName.HIRING_MANAGER,
        RoleName.INTERVIEWER,
        RoleName.EMPLOYEE,
    }
)


class InviteUserRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    roles: list[RoleName] = Field(min_length=1, max_length=4)
    job_title: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=32)
    department_id: uuid.UUID | None = None

    @field_validator("roles")
    @classmethod
    def _grantable(cls, value: list[RoleName]) -> list[RoleName]:
        invalid = [r for r in value if r not in GRANTABLE_ROLES]
        if invalid:
            raise ValueError(
                f"These roles cannot be granted here: {', '.join(r.value for r in invalid)}"
            )
        return value


class UpdateRolesRequest(BaseModel):
    roles: list[RoleName] = Field(min_length=1, max_length=4)

    @field_validator("roles")
    @classmethod
    def _grantable(cls, value: list[RoleName]) -> list[RoleName]:
        invalid = [r for r in value if r not in GRANTABLE_ROLES]
        if invalid:
            raise ValueError(
                f"These roles cannot be granted here: {', '.join(r.value for r in invalid)}"
            )
        return value


class UpdateUserRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    job_title: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=32)
    department_id: uuid.UUID | None = None


class StatusChangeRequest(BaseModel):
    status: UserStatus
    reason: str | None = Field(default=None, max_length=500)


class InviteResponse(BaseModel):
    user: UserProfile
    #: Truthful: the invitation may not have been transmitted.
    invitation_email_status: str
    #: Returned only when the email could not be sent, so an admin can still onboard them.
    setup_link: str | None = None
    message: str


class RoleOut(BaseModel):
    name: str
    description: str
    grantable: bool


@router.get(
    "/roles",
    response_model=SuccessResponse[list[RoleOut]],
    summary="List assignable roles",
    dependencies=[Depends(require_permission(Perm.USER_READ))],
)
async def list_roles() -> SuccessResponse[list[RoleOut]]:
    return SuccessResponse(
        data=[
            RoleOut(
                name=role.value,
                description=ROLE_DESCRIPTIONS.get(role, ""),
                grantable=role in GRANTABLE_ROLES,
            )
            for role in RoleName
        ]
    )


@router.get(
    "",
    response_model=SuccessResponse[Page[UserProfile]],
    summary="List company users",
    dependencies=[Depends(require_permission(Perm.USER_READ))],
)
async def list_users(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query(description="Name or email")] = None,
    role: RoleName | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
) -> SuccessResponse[Page[UserProfile]]:
    stmt = (
        select(User)
        .where(User.company_id == company_id, User.deleted_at.is_(None))
        .options(selectinload(User.roles))
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if user_status:
        stmt = stmt.where(User.status == user_status)
    if role:
        from app.models.user import UserRole

        stmt = stmt.where(
            User.id.in_(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name == role.value)
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(User.first_name)
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
            [UserProfile.model_validate(u) for u in rows],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "",
    response_model=SuccessResponse[InviteResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Invite a staff member",
    description=(
        "Creates a company user and emails them a link to set their password. The "
        "account starts inactive until they do. If no email provider is configured the "
        "response returns the setup link so the admin can share it directly."
    ),
    dependencies=[Depends(require_permission(Perm.USER_CREATE))],
)
async def invite_user(
    payload: InviteUserRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[InviteResponse]:
    email = payload.email.strip().lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise DuplicateResource(
            "An account with this email already exists on the platform",
            code="EMAIL_ALREADY_REGISTERED",
        )

    roles = await _resolve_roles(session, payload.roles, company_id)

    user = User(
        email=email,
        # A random unusable password: the invitee sets their own via the emailed link.
        hashed_password=hash_password(generate_url_token()),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        job_title=payload.job_title,
        phone=payload.phone,
        company_id=company_id,
        department_id=payload.department_id,
        status=UserStatus.PENDING_VERIFICATION,
    )
    user.roles.extend(roles)
    session.add(user)
    await session.flush()

    auth = AuthService(session)
    raw_token = await auth.issue_verification_token(user, PURPOSE_PASSWORD_RESET)
    await session.flush()

    setup_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}&setup=1"

    from app.modules.auth.router import _send_account_email

    email_status = await _send_account_email(
        to=user.email,
        subject=f"You have been invited to {principal.user.company.name if principal.user.company else 'HireHQ'}",
        heading="Set up your HireHQ account",
        body=(
            f"{principal.full_name} has invited you to join as "
            f"{', '.join(r.value.replace('_', ' ').title() for r in payload.roles)}. "
            "Set your password to get started."
        ),
        link=setup_link,
        cta="Set your password",
    )

    await AuditService(session).record_for(
        principal,
        action=AuditAction.CREATE,
        entity_type="User",
        entity_id=user.id,
        summary=f"Invited {email} as {', '.join(r.value for r in payload.roles)}",
    )

    transmitted = email_status.value == "SENT"
    message = (
        "Invitation sent"
        if transmitted
        else (
            "User created, but the invitation email was not transmitted because no email "
            "provider is configured. Share the setup link with them directly."
        )
    )
    return SuccessResponse(
        data=InviteResponse(
            user=UserProfile.model_validate(user),
            invitation_email_status=email_status.value,
            setup_link=None if transmitted else setup_link,
            message=message,
        ),
        message=message,
    )


async def _resolve_roles(
    session: AsyncSession, names: list[RoleName], company_id: uuid.UUID
) -> list[Role]:
    roles = (
        (
            await session.execute(
                select(Role).where(
                    Role.name.in_([r.value for r in names]),
                    Role.company_id.is_(None),
                    Role.is_system.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    found = {r.name for r in roles}
    missing = {r.value for r in names} - found
    if missing:
        raise ValidationError(
            f"Unknown roles: {', '.join(sorted(missing))}. Run the database seed."
        )
    return list(roles)


async def _load_user(
    session: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID
) -> User:
    user = (
        (
            await session.execute(
                select(User)
                .where(
                    User.id == user_id,
                    User.company_id == company_id,
                    User.deleted_at.is_(None),
                )
                .options(selectinload(User.roles))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if user is None:
        raise ResourceNotFound("User", user_id)
    return user


@router.get(
    "/{user_id}",
    response_model=SuccessResponse[UserProfile],
    summary="Get a company user",
    dependencies=[Depends(require_permission(Perm.USER_READ))],
)
async def get_user(
    user_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[UserProfile]:
    user = await _load_user(session, company_id, user_id)
    return SuccessResponse(data=UserProfile.model_validate(user))


@router.patch(
    "/{user_id}",
    response_model=SuccessResponse[UserProfile],
    summary="Update a company user",
    dependencies=[Depends(require_permission(Perm.USER_UPDATE))],
)
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[UserProfile]:
    user = await _load_user(session, company_id, user_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await session.flush()
    return SuccessResponse(data=UserProfile.model_validate(user), message="User updated")


@router.put(
    "/{user_id}/roles",
    response_model=SuccessResponse[UserProfile],
    summary="Replace a user's roles",
    dependencies=[Depends(require_permission(Perm.ROLE_MANAGE))],
)
async def update_roles(
    user_id: uuid.UUID,
    payload: UpdateRolesRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[UserProfile]:
    user = await _load_user(session, company_id, user_id)
    previous = sorted(user.role_names)

    if user.id == principal.id and RoleName.COMPANY_ADMIN not in payload.roles:
        # Prevent an admin locking themselves - and possibly the whole tenant - out.
        raise BusinessRuleError(
            "You cannot remove your own company-admin role. Ask another admin to do it.",
            code="CANNOT_DEMOTE_SELF",
        )

    if RoleName.COMPANY_ADMIN.value in previous and RoleName.COMPANY_ADMIN not in payload.roles:
        remaining = await _count_company_admins(session, company_id, exclude=user.id)
        if remaining == 0:
            raise BusinessRuleError(
                "This is the last company admin. Promote someone else first.",
                code="LAST_COMPANY_ADMIN",
            )

    roles = await _resolve_roles(session, payload.roles, company_id)
    user.roles.clear()
    user.roles.extend(roles)
    await session.flush()

    # Permissions changed, so outstanding tokens must be re-issued.
    await AuthService(session).revoke_all_sessions(user.id, reason="roles_changed")

    await AuditService(session).record_for(
        principal,
        action=AuditAction.PERMISSION_CHANGE,
        entity_type="User",
        entity_id=user.id,
        summary=f"Changed roles for {user.email}",
        changes={"roles": {"from": previous, "to": sorted(r.value for r in payload.roles)}},
    )
    return SuccessResponse(
        data=UserProfile.model_validate(user),
        message="Roles updated. The user must sign in again.",
    )


async def _count_company_admins(
    session: AsyncSession, company_id: uuid.UUID, *, exclude: uuid.UUID | None = None
) -> int:
    from app.models.user import UserRole

    stmt = (
        select(func.count())
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.company_id == company_id,
            User.deleted_at.is_(None),
            User.status == UserStatus.ACTIVE,
            Role.name == RoleName.COMPANY_ADMIN.value,
        )
    )
    if exclude:
        stmt = stmt.where(User.id != exclude)
    return (await session.execute(stmt)).scalar_one()


@router.post(
    "/{user_id}/status",
    response_model=SuccessResponse[UserProfile],
    summary="Activate or deactivate a user",
    description="Deactivating immediately signs the user out of every device.",
    dependencies=[Depends(require_permission(Perm.USER_UPDATE))],
)
async def change_status(
    user_id: uuid.UUID,
    payload: StatusChangeRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[UserProfile]:
    user = await _load_user(session, company_id, user_id)
    if user.id == principal.id and payload.status != UserStatus.ACTIVE:
        raise BusinessRuleError("You cannot deactivate your own account")

    if (
        RoleName.COMPANY_ADMIN.value in user.role_names
        and payload.status != UserStatus.ACTIVE
        and await _count_company_admins(session, company_id, exclude=user.id) == 0
    ):
        raise BusinessRuleError(
            "This is the last active company admin and cannot be deactivated",
            code="LAST_COMPANY_ADMIN",
        )

    previous = user.status
    user.status = payload.status
    await session.flush()

    if payload.status != UserStatus.ACTIVE:
        await AuthService(session).revoke_all_sessions(user.id, reason="deactivated")

    await AuditService(session).record_for(
        principal,
        action=AuditAction.STATUS_CHANGE,
        entity_type="User",
        entity_id=user.id,
        summary=f"{user.email} moved from {previous.value} to {payload.status.value}",
        meta={"reason": payload.reason},
    )
    return SuccessResponse(
        data=UserProfile.model_validate(user),
        message=f"User is now {payload.status.value.lower()}",
    )


@router.delete(
    "/{user_id}",
    response_model=SuccessResponse[dict],
    summary="Remove a user from the company",
    description="Soft-deletes the account so audit history and past activity survive.",
    dependencies=[Depends(require_permission(Perm.USER_DELETE))],
)
async def delete_user(
    user_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[dict]:
    user = await _load_user(session, company_id, user_id)
    if user.id == principal.id:
        raise BusinessRuleError("You cannot delete your own account")
    if (
        RoleName.COMPANY_ADMIN.value in user.role_names
        and await _count_company_admins(session, company_id, exclude=user.id) == 0
    ):
        raise BusinessRuleError(
            "This is the last company admin and cannot be removed", code="LAST_COMPANY_ADMIN"
        )

    user.deleted_at = datetime.now(UTC)
    user.status = UserStatus.INACTIVE
    await session.flush()
    await AuthService(session).revoke_all_sessions(user.id, reason="user_deleted")

    await AuditService(session).record_for(
        principal,
        action=AuditAction.DELETE,
        entity_type="User",
        entity_id=user.id,
        summary=f"Removed {user.email} from the company",
    )
    return SuccessResponse(
        data={"id": str(user_id), "deleted": True}, message="User removed"
    )
