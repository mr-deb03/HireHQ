"""Users, roles, permissions and auth-token records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RoleName, UserStatus
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, UTCDateTime

if TYPE_CHECKING:
    from app.models.company import Company, Department


class Permission(Base, UUIDMixin, TimestampMixin):
    """A single ``resource:action`` grant."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))

    # Never traversed in application code, and eager-loading it would pull the whole
    # role graph on every permission touch.
    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions", lazy="noload"
    )


class Role(Base, UUIDMixin, TimestampMixin):
    """A named bundle of permissions.

    Built-in roles (``is_system=True``) are reconciled against
    ``app.core.permissions.ROLE_PERMISSIONS`` on startup and cannot be deleted. Company
    admins may create additional roles scoped to their own company.
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", "company_id", name="uq_role_name_company"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: NULL for built-in platform roles; set for company-defined custom roles.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )

    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions", back_populates="roles", lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(
        secondary="user_roles", back_populates="roles", lazy="noload"
    )

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for p in self.permissions}


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A login identity.

    ``company_id`` is NULL for super admins and for candidates: a candidate account is
    global so one person can apply across every company on the platform, while their
    *candidate record* inside each company is a separate, tenant-scoped row.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_company_status", "company_id", "status"),
        Index("ix_users_email_lower", "email"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    job_title: Mapped[str | None] = mapped_column(String(150))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, native_enum=False, length=32),
        default=UserStatus.PENDING_VERIFICATION,
        nullable=False,
        index=True,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    phone_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: Any access token issued before this instant is rejected. Bumped on password
    #: change, deactivation and "sign out everywhere".
    tokens_valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime())

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )

    notification_preferences: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    company: Mapped[Company | None] = relationship(
        back_populates="users", lazy="joined", foreign_keys=[company_id]
    )
    #: ``foreign_keys`` is required because Department also points back at User
    #: (``Department.head_user_id``), so the join is otherwise ambiguous.
    department: Mapped[Department | None] = relationship(
        lazy="noload", foreign_keys=[department_id]
    )
    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )

    # --------------------------------------------------------------- helpers
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def role_names(self) -> set[str]:
        return {r.name for r in self.roles}

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE and self.deleted_at is None

    def has_role(self, role: RoleName | str) -> bool:
        return str(role) in self.role_names

    @property
    def is_super_admin(self) -> bool:
        return self.has_role(RoleName.SUPER_ADMIN)


class RefreshToken(Base, UUIDMixin, TimestampMixin):
    """Server-side record of an issued refresh token, enabling revocation and rotation.

    Only the JWT id is stored - never the token itself - so the table is useless to an
    attacker who reads it.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),)

    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: Set when this token was rotated, pointing at its replacement. A refresh attempt
    #: with an already-rotated token indicates replay and revokes the whole chain.
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class VerificationToken(Base, UUIDMixin, TimestampMixin):
    """Single-use token for email verification and password reset (digest only)."""

    __tablename__ = "verification_tokens"
    __table_args__ = (Index("ix_verification_tokens_user_purpose", "user_id", "purpose"),)

    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # EMAIL_VERIFY | PASSWORD_RESET
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)


class DataRequest(Base, UUIDMixin, TimestampMixin):
    """GDPR-style data export / deletion request raised by a candidate (privacy, s49)."""

    __tablename__ = "data_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)  # EXPORT | DELETE
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    result_object_key: Mapped[str | None] = mapped_column(String(512))
