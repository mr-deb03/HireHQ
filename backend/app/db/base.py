"""Declarative base and the mixins every table is built from."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.db.types import GUID, UTCDateTime

#: Explicit naming convention so Alembic autogenerate produces stable, diffable
#: constraint names instead of database-assigned ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDMixin:
    """Public identifiers are UUIDs so ids are never guessable or enumerable."""

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4, sort_order=-100
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True, sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False, sort_order=101
    )


class SoftDeleteMixin:
    """Soft deletion, so audit trails and analytics never lose their referents."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), default=None, nullable=True, index=True, sort_order=102
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TenantMixin:
    """Marks a table as company-scoped.

    Every model carrying this mixin is subject to tenant filtering: repositories that
    inherit ``TenantRepository`` refuse to build a query without a company scope, which
    is what structurally prevents Company A from reading Company B's data.
    """

    @declared_attr
    @classmethod
    def company_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            GUID(),
            ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            sort_order=-99,
        )


class SlugMixin:
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


def tenant_index(table_name: str, *columns: str, unique: bool = False) -> Index:
    """Composite index leading with ``company_id`` - the shape every tenant query uses."""
    name = f"ix_{table_name}_company_{'_'.join(columns)}"
    return Index(name, "company_id", *columns, unique=unique)
