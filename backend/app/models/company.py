"""Company (tenant), departments and office locations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CompanySize, CompanyStatus
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.user import User


class Company(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """The tenant boundary. Everything company-scoped hangs off this row."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(512))
    website: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(120), index=True)
    size: Mapped[CompanySize | None] = mapped_column(
        SAEnum(CompanySize, native_enum=False, length=20)
    )
    founded_year: Mapped[int | None] = mapped_column()

    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    headquarters: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[CompanyStatus] = mapped_column(
        SAEnum(CompanyStatus, native_enum=False, length=20),
        default=CompanyStatus.TRIAL,
        nullable=False,
        index=True,
    )
    subscription_plan: Mapped[str] = mapped_column(String(50), default="trial", nullable=False)
    #: Free-form tenant configuration: ATS defaults, reminder offsets, pipeline stages,
    #: enabled channels. Read through ``CompanySettingsService`` which applies defaults.
    settings: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    social_links: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    users: Mapped[list[User]] = relationship(
        back_populates="company", lazy="noload", foreign_keys="User.company_id"
    )
    departments: Mapped[list[Department]] = relationship(
        back_populates="company", lazy="noload", cascade="all, delete-orphan"
    )
    locations: Mapped[list[CompanyLocation]] = relationship(
        back_populates="company", lazy="noload", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="company", lazy="noload")


class Department(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_department_company_name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    head_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped[Company] = relationship(back_populates="departments", lazy="noload")


class CompanyLocation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "company_locations"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_headquarters: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped[Company] = relationship(back_populates="locations", lazy="noload")

    @property
    def display(self) -> str:
        parts = [p for p in (self.city, self.state, self.country) if p]
        return ", ".join(parts) or self.name
