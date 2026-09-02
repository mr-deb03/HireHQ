"""Authentication and authorisation dependencies.

``get_current_user`` resolves and validates the bearer token; ``require_permission`` and
``require_roles`` are dependency *factories* used to declare access on each route. Tenant
scope comes from the authenticated principal - never from a client-supplied company id -
which is what makes cross-tenant access impossible to request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import RoleName, UserStatus
from app.core.exceptions import (
    AccountInactive,
    AuthenticationError,
    EmailNotVerified,
    InvalidToken,
    PermissionDenied,
    TokenExpired,
)
from app.core.logging import company_id_ctx, user_id_ctx
from app.core.permissions import permissions_for_roles
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.providers.email import email_verification_required

#: ``auto_error=False`` so a missing header raises our own envelope-shaped 401 rather
#: than FastAPI's bare ``{"detail": ...}``.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


@dataclass(slots=True)
class Principal:
    """The authenticated caller, with everything authorisation needs pre-resolved."""

    user: User
    permissions: frozenset[str]
    roles: frozenset[str]

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def company_id(self) -> uuid.UUID | None:
        return self.user.company_id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def full_name(self) -> str:
        return self.user.full_name

    @property
    def is_super_admin(self) -> bool:
        return RoleName.SUPER_ADMIN in self.roles

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)

    def has_role(self, *roles: RoleName | str) -> bool:
        return any(str(r) in self.roles for r in roles)

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDenied(
                f"This action requires the '{permission}' permission",
                details={"required_permission": permission},
            )

    def assert_company(self, company_id: uuid.UUID | None) -> None:
        """Refuse access to another tenant's row.

        Raises the 404-shaped ``TenantIsolationViolation`` so probing cannot distinguish
        "exists elsewhere" from "does not exist".
        """
        if self.is_super_admin:
            return
        if company_id is None or company_id != self.company_id:
            from app.core.exceptions import TenantIsolationViolation

            raise TenantIsolationViolation()


async def _load_user(session: AsyncSession, user_id: str) -> User | None:
    stmt = (
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .options(selectinload(User.roles))
    )
    return (await session.execute(stmt)).unique().scalar_one_or_none()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("An access token is required")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.PyJWTError as exc:
        raise InvalidToken() from exc

    user = await _load_user(session, payload["sub"])
    if user is None:
        raise InvalidToken("The account for this token no longer exists")

    if user.status == UserStatus.PENDING_VERIFICATION and email_verification_required():
        raise EmailNotVerified()
    if user.status in (UserStatus.INACTIVE, UserStatus.SUSPENDED):
        raise AccountInactive(f"This account is {user.status.value.lower()}")

    # A password change or forced sign-out bumps ``tokens_valid_from``, instantly
    # invalidating every access token issued before it without a revocation list.
    if user.tokens_valid_from is not None:
        issued_at = datetime.fromtimestamp(payload.get("iat", 0), tz=UTC)
        if issued_at < user.tokens_valid_from:
            raise TokenExpired("Your session is no longer valid, please sign in again")

    roles = frozenset(user.role_names)
    permissions = set(permissions_for_roles(list(roles)))
    # Custom company roles carry their grants in the database rather than the static
    # matrix, so merge those in too.
    for role in user.roles:
        if not role.is_system:
            permissions |= role.permission_codes

    principal = Principal(user=user, permissions=frozenset(permissions), roles=roles)

    user_id_ctx.set(str(user.id))
    if user.company_id:
        company_id_ctx.set(str(user.company_id))
    request.state.principal = principal
    return principal


CurrentUser = Annotated[Principal, Depends(get_current_user)]


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal | None:
    """For public endpoints that behave differently when signed in (e.g. job listings
    showing whether the viewer has already applied)."""
    if credentials is None:
        return None
    try:
        return await get_current_user(request, credentials, session)
    except AuthenticationError:
        return None


OptionalUser = Annotated[Principal | None, Depends(get_optional_user)]


def require_permission(*permissions: str, require_all: bool = False):
    """Dependency factory: caller must hold these permission(s)."""

    async def dependency(principal: CurrentUser) -> Principal:
        granted = (
            all(principal.has(p) for p in permissions)
            if require_all
            else principal.has_any(*permissions)
        )
        if not granted:
            raise PermissionDenied(
                "You do not have permission to perform this action",
                details={
                    "required_permissions": list(permissions),
                    "mode": "all" if require_all else "any",
                },
            )
        return principal

    return dependency


def require_roles(*roles: RoleName | str):
    """Dependency factory: caller must hold one of these roles.

    Prefer ``require_permission`` - roles are for the handful of cases where the *role
    itself* is the concept (e.g. candidate-only self-service endpoints)."""

    async def dependency(principal: CurrentUser) -> Principal:
        if not principal.has_role(*roles):
            raise PermissionDenied(
                "This area is not available for your role",
                details={"required_roles": [str(r) for r in roles]},
            )
        return principal

    return dependency


async def require_company(principal: CurrentUser) -> uuid.UUID:
    """Resolve the tenant for a company-scoped route.

    Super admins have no company of their own; they must act through the admin API,
    which selects a tenant explicitly and audits it.
    """
    if principal.company_id is None:
        raise PermissionDenied(
            "This endpoint operates on a company. Your account is not attached to one.",
            code="NO_COMPANY_CONTEXT",
        )
    return principal.company_id


CompanyScope = Annotated[uuid.UUID, Depends(require_company)]


async def require_super_admin(principal: CurrentUser) -> Principal:
    if not principal.is_super_admin:
        raise PermissionDenied("This action is restricted to platform administrators")
    return principal


SuperAdmin = Annotated[Principal, Depends(require_super_admin)]
