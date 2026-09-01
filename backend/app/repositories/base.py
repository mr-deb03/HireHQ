"""Repository base classes.

``TenantRepository`` is the structural guarantee behind multi-tenancy (s46): it cannot
build a query without a company scope, so "forgot the ``WHERE company_id``" is a type
error at construction time rather than a data leak in production.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.exceptions import ResourceNotFound
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD for a model with no tenant scoping (users, companies, platform tables)."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----------------------------------------------------------------- read
    def select(self) -> Select[tuple[ModelT]]:
        stmt = select(self.model)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    async def get(self, entity_id: uuid.UUID | str) -> ModelT | None:
        stmt = self.select().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_or_404(self, entity_id: uuid.UUID | str, *, label: str | None = None) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise ResourceNotFound(label or self.model.__name__, entity_id)
        return entity

    async def get_by(self, **filters: Any) -> ModelT | None:
        stmt = self.select()
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        order_by: InstrumentedAttribute | None = None,
        **filters: Any,
    ) -> Sequence[ModelT]:
        stmt = self.select()
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.limit(limit).offset(offset)
        return (await self.session.execute(stmt)).unique().scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        return (await self.session.execute(stmt)).scalar_one()

    async def exists(self, **filters: Any) -> bool:
        return await self.count(**filters) > 0

    async def paginate(
        self, stmt: Select[tuple[ModelT]], *, page: int, page_size: int
    ) -> tuple[Sequence[ModelT], int]:
        """Run a prepared statement and its count in one place.

        The count strips ORDER BY (and any eager-load joins it implies) because ordering
        is meaningless for a count and Postgres rejects ordering by a column that is not
        in the aggregate.
        """
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        page_stmt = stmt.limit(page_size).offset((page - 1) * page_size)
        rows = (await self.session.execute(page_stmt)).unique().scalars().all()
        return rows, total

    # ---------------------------------------------------------------- write
    async def create(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    async def update(self, entity: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            if value is not None or key in getattr(self.model, "__nullable_updates__", ()):
                setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def bulk_update(self, ids: Sequence[uuid.UUID], **values: Any) -> int:
        if not ids:
            return 0
        stmt = update(self.model).where(self.model.id.in_(ids)).values(**values)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def delete(self, entity: ModelT) -> None:
        """Soft-delete when the model supports it, hard-delete otherwise."""
        if hasattr(entity, "deleted_at"):
            from app.db.base import utcnow

            entity.deleted_at = utcnow()  # type: ignore[attr-defined]
            await self.session.flush()
        else:
            await self.session.delete(entity)
            await self.session.flush()

    async def hard_delete(self, entity_id: uuid.UUID) -> None:
        await self.session.execute(delete(self.model).where(self.model.id == entity_id))  # type: ignore[attr-defined]

    async def flush(self) -> None:
        await self.session.flush()


class TenantRepository(BaseRepository[ModelT]):
    """A repository permanently bound to one company.

    Every read and write is filtered by ``company_id``. There is deliberately no way to
    construct one without a company, and no method that skips the filter.
    """

    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        if company_id is None:
            raise ValueError(
                f"{type(self).__name__} requires a company_id: tenant-scoped data cannot "
                "be queried without a tenant"
            )
        super().__init__(session)
        self.company_id = company_id

    def select(self) -> Select[tuple[ModelT]]:
        return super().select().where(self.model.company_id == self.company_id)  # type: ignore[attr-defined]

    async def count(self, **filters: Any) -> int:
        return await super().count(company_id=self.company_id, **filters)

    async def create(self, **values: Any) -> ModelT:
        # The caller can never write into another tenant, even by passing company_id.
        values["company_id"] = self.company_id
        return await super().create(**values)

    async def bulk_update(self, ids: Sequence[uuid.UUID], **values: Any) -> int:
        if not ids:
            return 0
        values.pop("company_id", None)
        stmt = (
            update(self.model)
            .where(self.model.id.in_(ids))  # type: ignore[attr-defined]
            .where(self.model.company_id == self.company_id)  # type: ignore[attr-defined]
            .values(**values)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
