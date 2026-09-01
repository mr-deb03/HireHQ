"""Shared request/response schema building blocks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination(
    page: Annotated[int, Query(ge=1, le=10_000, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> PaginationParams:
    """Reusable pagination dependency."""
    return PaginationParams(page=page, page_size=page_size)


class IdList(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class BulkResult(BaseModel):
    requested: int
    succeeded: list[str] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)
    #: Present on status-change bulk actions.
    new_status: str | None = None


class UserRef(ORMModel):
    """Minimal user reference embedded in other responses."""

    id: uuid.UUID
    full_name: str
    email: str
    avatar_url: str | None = None
    job_title: str | None = None


class Timestamped(ORMModel):
    created_at: datetime
    updated_at: datetime


class DeleteResponse(BaseModel):
    id: uuid.UUID
    deleted: bool = True
    message: str


class CountResponse(BaseModel):
    count: int
