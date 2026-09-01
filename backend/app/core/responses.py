"""Standard API response envelope and pagination primitives.

Every successful response is ``{"success": true, "data": ..., "message": ...}`` and every
failure is ``{"success": false, "error": {"code": ..., "message": ...}}``.
"""

from __future__ import annotations

from math import ceil
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(examples=["APPLICATION_NOT_FOUND"])
    message: str = Field(examples=["Application not found"])
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    request_id: str | None = None


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str | None = None


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class Page(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, items: list[T], *, page: int, page_size: int, total: int) -> Page[T]:
        total_pages = max(1, ceil(total / page_size)) if page_size else 1
        return cls(
            items=items,
            meta=PageMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )


def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
    """Build a success envelope for routes that return raw dicts."""
    return {"success": True, "data": data, "message": message}


def error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return {"success": False, "error": payload}
