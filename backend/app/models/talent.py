"""Talent pools and employee referrals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ReferralStatus
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime


class TalentPool(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A named, reusable group of candidates."""

    __tablename__ = "talent_pools"
    __table_args__ = (Index("ix_talent_pools_company_name", "company_id", "name", unique=True),)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    #: Optional saved-search definition. When set, the pool can be refreshed to pull in
    #: newly matching candidates. Uses the same allow-listed field grammar as workflows.
    criteria: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    is_dynamic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    colour: Mapped[str | None] = mapped_column(String(20))
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    members: Mapped[list[TalentPoolMember]] = relationship(
        back_populates="pool", lazy="noload", cascade="all, delete-orphan"
    )


class TalentPoolMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "talent_pool_members"
    __table_args__ = (
        Index("ix_talent_pool_members_pool_candidate", "pool_id", "candidate_id", unique=True),
    )

    pool_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("talent_pools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    #: Score at the moment of adding, so a pool keeps context even after re-scoring.
    snapshot_ats_score: Mapped[float | None] = mapped_column(Numeric(5, 2))

    pool: Mapped[TalentPool] = relationship(back_populates="members", lazy="noload")


class Referral(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """An employee referring someone for a job."""

    __tablename__ = "referrals"
    __table_args__ = (
        Index("ix_referrals_company_status", "company_id", "status"),
        Index("ix_referrals_referrer", "referrer_id"),
    )

    referrer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    #: Populated once the referred person actually has a candidate record.
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="SET NULL"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="SET NULL")
    )

    referred_name: Mapped[str] = mapped_column(String(200), nullable=False)
    referred_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    referred_phone: Mapped[str | None] = mapped_column(String(32))
    #: How the referrer knows them - context for the recruiter, not a scoring input.
    relationship_to_referrer: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    resume_object_key: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[ReferralStatus] = mapped_column(
        SAEnum(ReferralStatus, native_enum=False, length=20),
        default=ReferralStatus.REFERRED,
        nullable=False,
        index=True,
    )
    status_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    bonus_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    bonus_paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tags: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
