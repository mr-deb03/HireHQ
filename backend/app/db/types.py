"""Portable column types.

HireHQ targets PostgreSQL, but the whole backend (and the test-suite) must also run
with zero infrastructure on SQLite. These decorators pick the native PostgreSQL type
when available and fall back to a faithful SQLite representation otherwise, so model
code never branches on the dialect.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.types import JSON


class GUID(TypeDecorator):
    """UUID column: native ``uuid`` on PostgreSQL, 36-char string elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONType(TypeDecorator):
    """JSONB on PostgreSQL (indexable, typed), plain JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime that is *always* stored and returned in UTC.

    SQLite has no timezone support, so naive values coming back from it are re-tagged as
    UTC. This prevents the classic bug where interview reminders compare an aware
    ``now()`` against a naive column and raise ``TypeError`` at runtime.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StringArray(TypeDecorator):
    """A list of short strings (skills, tags, keywords) stored as JSON.

    Deliberately JSON rather than ``ARRAY(Text)``: it keeps the model portable and these
    lists are always read whole, never queried element-wise in a hot path (skill *search*
    goes through the normalised ``candidate_skills`` / ``job_skills`` tables instead).
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[str] | None, dialect: Any) -> Any:
        return list(value) if value is not None else None

    def process_result_value(self, value: Any, dialect: Any) -> list[str]:
        return list(value) if value else []
