"""Offers and the onboarding handoff."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OfferStatus, OnboardingStatus
from app.db.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONType, StringArray, UTCDateTime


class Offer(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "offers"
    __table_args__ = (
        Index("ix_offers_company_status", "company_id", "status"),
        Index("ix_offers_application", "application_id"),
        Index("ix_offers_expires", "expires_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    reference_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    position_title: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(150))
    location: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[str | None] = mapped_column(String(30))

    base_salary: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    variable_pay: Mapped[float | None] = mapped_column(Numeric(14, 2))
    joining_bonus: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    salary_period: Mapped[str] = mapped_column(String(16), default="YEARLY", nullable=False)
    benefits: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)

    joining_date: Mapped[date | None] = mapped_column(Date, index=True)
    probation_months: Mapped[int | None] = mapped_column(Integer)
    reporting_to: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    status: Mapped[OfferStatus] = mapped_column(
        SAEnum(OfferStatus, native_enum=False, length=20),
        default=OfferStatus.DRAFT,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: Candidate's own words when declining - kept for analytics on why offers are lost.
    decline_reason: Mapped[str | None] = mapped_column(String(500))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    #: Generated offer letter in object storage. Confidential: signed-URL access only.
    document_object_key: Mapped[str | None] = mapped_column(String(512))
    document_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: Single-use token letting the candidate view and respond without a full login.
    access_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)

    onboarding: Mapped[Onboarding | None] = relationship(
        back_populates="offer", lazy="noload", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def total_compensation(self) -> float:
        return float(self.base_salary) + float(self.variable_pay or 0) + float(self.joining_bonus or 0)


class Onboarding(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "onboarding"
    __table_args__ = (Index("ix_onboarding_company_status", "company_id", "status"),)

    offer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[OnboardingStatus] = mapped_column(
        SAEnum(OnboardingStatus, native_enum=False, length=30),
        default=OnboardingStatus.PREBOARDING,
        nullable=False,
        index=True,
    )
    expected_joining_date: Mapped[date | None] = mapped_column(Date, index=True)
    actual_joining_date: Mapped[date | None] = mapped_column(Date)
    buddy_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Set when the candidate has been converted into an internal employee account.
    employee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)

    offer: Mapped[Offer] = relationship(back_populates="onboarding", lazy="noload")
    tasks: Mapped[list[OnboardingTask]] = relationship(
        back_populates="onboarding",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OnboardingTask.display_order",
    )

    @property
    def completion_percentage(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.completed_at is not None)
        return round(done / len(self.tasks) * 100, 1)


class OnboardingTask(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "onboarding_tasks"

    onboarding_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("onboarding.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    #: DOCUMENT | VERIFICATION | IT_SETUP | HR | TRAINING
    category: Mapped[str] = mapped_column(String(30), default="HR", nullable=False)
    #: CANDIDATE | COMPANY - who has to act.
    owner_type: Mapped[str] = mapped_column(String(20), default="CANDIDATE", nullable=False)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Link to the uploaded document that satisfies this task, when applicable.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("candidate_documents.id", ondelete="SET NULL")
    )

    onboarding: Mapped[Onboarding] = relationship(back_populates="tasks", lazy="noload")
