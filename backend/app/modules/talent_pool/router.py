"""Talent pool endpoints, including AI-assisted matching to a new job."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.modules.candidates.schemas import CandidateSummaryOut
from app.modules.talent_pool.service import TalentPoolService
from app.schemas.common import DeleteResponse, ORMModel, PaginationParams, pagination

router = APIRouter(prefix="/talent-pool", tags=["Talent Pool"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class PoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    colour: str | None = Field(default=None, max_length=20)
    #: Optional saved search, so the pool can be refreshed as new candidates arrive.
    criteria: dict | None = None


class PoolOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    criteria: dict = Field(default_factory=dict)
    is_dynamic: bool
    colour: str | None = None
    member_count: int
    created_at: datetime


class AddMemberRequest(BaseModel):
    candidate_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2000)


class MatchOut(BaseModel):
    candidate_id: str
    full_name: str
    email: str
    current_designation: str | None = None
    total_experience_years: float
    score: float
    recommendation: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    summary: str


@router.get(
    "",
    response_model=SuccessResponse[list[PoolOut]],
    summary="List talent pools",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_READ))],
)
async def list_pools(
    company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[PoolOut]]:
    pools = await TalentPoolService(session, company_id).list_pools()
    return SuccessResponse(data=[PoolOut.model_validate(p) for p in pools])


@router.post(
    "",
    response_model=SuccessResponse[PoolOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a talent pool",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def create_pool(
    payload: PoolCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[PoolOut]:
    service = TalentPoolService(session, company_id)
    pool = await service.create(
        name=payload.name,
        description=payload.description,
        criteria=payload.criteria,
        colour=payload.colour,
        created_by_id=principal.id,
    )
    return SuccessResponse(data=PoolOut.model_validate(pool), message="Talent pool created")


@router.get(
    "/{pool_id}/members",
    response_model=SuccessResponse[Page[CandidateSummaryOut]],
    summary="List pool members",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_READ))],
)
async def list_members(
    pool_id: uuid.UUID,
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
) -> SuccessResponse[Page[CandidateSummaryOut]]:
    service = TalentPoolService(session, company_id)
    pool = await service.get(pool_id)
    members, total = await service.list_members(
        pool, page=page_params.page, page_size=page_params.page_size
    )
    return SuccessResponse(
        data=Page.build(
            [CandidateSummaryOut.model_validate(c) for c in members],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.post(
    "/{pool_id}/members",
    response_model=SuccessResponse[dict],
    summary="Add a candidate to a pool",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def add_member(
    pool_id: uuid.UUID,
    payload: AddMemberRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[dict]:
    service = TalentPoolService(session, company_id)
    pool = await service.get(pool_id)
    added = await service.add_candidate(
        pool, payload.candidate_id, note=payload.note, added_by_id=principal.id
    )
    return SuccessResponse(
        data={"added": added, "member_count": pool.member_count},
        message="Candidate added" if added else "Candidate is already in this pool",
    )


@router.delete(
    "/{pool_id}/members/{candidate_id}",
    response_model=SuccessResponse[dict],
    summary="Remove a candidate from a pool",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def remove_member(
    pool_id: uuid.UUID,
    candidate_id: uuid.UUID,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[dict]:
    service = TalentPoolService(session, company_id)
    pool = await service.get(pool_id)
    removed = await service.remove_candidate(pool, candidate_id)
    return SuccessResponse(
        data={"removed": removed, "member_count": pool.member_count},
        message="Candidate removed" if removed else "Candidate was not in this pool",
    )


@router.post(
    "/{pool_id}/refresh",
    response_model=SuccessResponse[dict],
    summary="Refresh a saved-search pool",
    description="Re-runs the pool's criteria and adds newly matching candidates.",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def refresh_pool(
    pool_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[dict]:
    service = TalentPoolService(session, company_id)
    pool = await service.get(pool_id)
    added = await service.refresh_dynamic_pool(pool)
    return SuccessResponse(
        data={"added": added, "member_count": pool.member_count},
        message=f"{added} new candidate(s) matched",
    )


@router.delete(
    "/{pool_id}",
    response_model=SuccessResponse[DeleteResponse],
    summary="Delete a talent pool",
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_MANAGE))],
)
async def delete_pool(
    pool_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[DeleteResponse]:
    service = TalentPoolService(session, company_id)
    pool = await service.get(pool_id)
    await service.delete(pool)
    return SuccessResponse(
        data=DeleteResponse(id=pool_id, message="Talent pool deleted"),
        message="Talent pool deleted",
    )


@router.get(
    "/match/{job_id}",
    response_model=SuccessResponse[list[MatchOut]],
    summary="Recommend existing candidates for a job",
    description=(
        "Scores candidates already in your database against a job using the same "
        "explainable ATS engine as live applications, so results are directly "
        "comparable. Candidates who already applied are excluded."
    ),
    dependencies=[Depends(require_permission(Perm.TALENT_POOL_READ))],
)
async def match_for_job(
    job_id: uuid.UUID,
    company_id: CompanyScope,
    session: DbSession,
    pool_id: Annotated[uuid.UUID | None, Query(description="Restrict to one pool")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    min_score: Annotated[float, Query(ge=0, le=100)] = 50,
) -> SuccessResponse[list[MatchOut]]:
    service = TalentPoolService(session, company_id)
    matches = await service.match_candidates_for_job(
        job_id, pool_id=pool_id, limit=limit, min_score=min_score
    )
    return SuccessResponse(
        data=[MatchOut(**m) for m in matches],
        message=f"{len(matches)} candidate(s) matched this role",
    )
