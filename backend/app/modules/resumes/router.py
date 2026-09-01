"""Resume upload, processing status and parsed-data endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import ResumeStatus
from app.core.exceptions import ResourceNotFound
from app.core.permissions import Perm
from app.core.responses import SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, require_permission
from app.models.resume import Resume
from app.modules.candidates.service import CandidateService
from app.modules.resumes.service import ResumeService
from app.providers.storage import get_storage
from app.schemas.common import ORMModel

router = APIRouter(prefix="/resumes", tags=["Resumes"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class ResumeAnalysisOut(ORMModel):
    parsed_name: str | None = None
    parsed_email: str | None = None
    parsed_phone: str | None = None
    parsed_location: str | None = None
    parsed_linkedin: str | None = None
    parsed_github: str | None = None
    parsed_portfolio: str | None = None
    skills: list = Field(default_factory=list)
    experience: list = Field(default_factory=list)
    education: list = Field(default_factory=list)
    certifications: list = Field(default_factory=list)
    projects: list = Field(default_factory=list)
    achievements: list = Field(default_factory=list)
    languages: list = Field(default_factory=list)
    total_experience_years: float | None = None
    current_designation: str | None = None
    current_company: str | None = None
    summary: str | None = None
    confidence: float
    parser_engine: str
    missing_fields: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)


class ResumeOut(ORMModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    status: ResumeStatus
    status_detail: str | None = None
    scan_status: str
    scan_engine: str | None = None
    scan_detail: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    is_primary: bool
    processing_attempts: int
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    created_at: datetime
    analysis: ResumeAnalysisOut | None = None
    download_url: str | None = None


class ResumeTextOut(BaseModel):
    resume_id: uuid.UUID
    text: str
    word_count: int
    page_count: int | None = None


class UploadResponse(BaseModel):
    resume: ResumeOut
    processing_queued: bool
    message: str


@router.post(
    "/candidates/{candidate_id}",
    response_model=SuccessResponse[UploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a resume for a candidate",
    description=(
        "Validates the file type and size, scans it, and stores it privately. Parsing "
        "and ATS re-scoring then run in the background. A file that fails validation or "
        "the security scan is rejected and never stored."
    ),
    dependencies=[Depends(require_permission(Perm.CANDIDATE_UPDATE))],
)
async def upload_resume(
    candidate_id: uuid.UUID,
    company_id: CompanyScope,
    session: DbSession,
    file: Annotated[UploadFile, File(description="PDF or DOCX")],
    make_primary: bool = True,
) -> SuccessResponse[UploadResponse]:
    candidate_service = CandidateService(session, company_id)
    candidate = await candidate_service.get(candidate_id)

    content = await file.read()
    service = ResumeService(session, company_id)
    resume = await service.upload(
        candidate=candidate,
        filename=file.filename or "resume.pdf",
        content=content,
        make_primary=make_primary,
    )
    resume_id = resume.id
    await session.commit()

    from app.workers.queue import get_queue

    await get_queue().enqueue(
        "process_resume", resume_id=str(resume_id), company_id=str(company_id)
    )

    payload = ResumeOut.model_validate(resume)
    payload.download_url = await get_storage().signed_url(resume.object_key)
    return SuccessResponse(
        data=UploadResponse(
            resume=payload,
            processing_queued=True,
            message="Resume accepted. Parsing is running in the background.",
        ),
        message="Resume uploaded",
    )


@router.get(
    "/{resume_id}",
    response_model=SuccessResponse[ResumeOut],
    summary="Get a resume and its parsed data",
    dependencies=[Depends(require_permission(Perm.CANDIDATE_DOCUMENT_READ))],
)
async def get_resume(
    resume_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ResumeOut]:
    resume = (
        (
            await session.execute(
                select(Resume)
                .where(Resume.id == resume_id, Resume.company_id == company_id)
                .options(selectinload(Resume.analysis))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if resume is None:
        raise ResourceNotFound("Resume", resume_id)

    payload = ResumeOut.model_validate(resume)
    payload.download_url = await get_storage().signed_url(resume.object_key)
    return SuccessResponse(data=payload)


@router.get(
    "/candidates/{candidate_id}",
    response_model=SuccessResponse[list[ResumeOut]],
    summary="List a candidate's resumes",
    dependencies=[Depends(require_permission(Perm.CANDIDATE_DOCUMENT_READ))],
)
async def list_resumes(
    candidate_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[ResumeOut]]:
    resumes = (
        (
            await session.execute(
                select(Resume)
                .where(Resume.candidate_id == candidate_id, Resume.company_id == company_id)
                .options(selectinload(Resume.analysis))
                .order_by(Resume.created_at.desc())
            )
        )
        .unique()
        .scalars()
        .all()
    )
    storage = get_storage()
    items: list[ResumeOut] = []
    for resume in resumes:
        payload = ResumeOut.model_validate(resume)
        payload.download_url = await storage.signed_url(resume.object_key)
        items.append(payload)
    return SuccessResponse(data=items)


@router.get(
    "/{resume_id}/text",
    response_model=SuccessResponse[ResumeTextOut],
    summary="Get the extracted resume text",
    description=(
        "The raw text the parser worked from. Useful for debugging a poor extraction. "
        "Treated as sensitive: it is never logged."
    ),
    dependencies=[Depends(require_permission(Perm.CANDIDATE_DOCUMENT_READ))],
)
async def get_resume_text(
    resume_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ResumeTextOut]:
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.company_id == company_id)
    )
    if resume is None:
        raise ResourceNotFound("Resume", resume_id)
    if not resume.extracted_text:
        raise ResourceNotFound("Extracted text for this resume", resume_id)

    return SuccessResponse(
        data=ResumeTextOut(
            resume_id=resume.id,
            text=resume.extracted_text,
            word_count=resume.word_count or 0,
            page_count=resume.page_count,
        )
    )


@router.post(
    "/{resume_id}/reprocess",
    response_model=SuccessResponse[ResumeOut],
    summary="Re-run parsing for a resume",
    description=(
        "Re-parses the stored file and merges the result into the candidate profile. "
        "Existing manually-entered data is preserved."
    ),
    dependencies=[Depends(require_permission(Perm.CANDIDATE_UPDATE))],
)
async def reprocess_resume(
    resume_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[ResumeOut]:
    service = ResumeService(session, company_id)
    resume = await service.process(resume_id)
    await session.commit()

    fresh = (
        (
            await session.execute(
                select(Resume)
                .where(Resume.id == resume_id)
                .options(selectinload(Resume.analysis))
            )
        )
        .unique()
        .scalar_one()
    )
    payload = ResumeOut.model_validate(fresh)
    payload.download_url = await get_storage().signed_url(fresh.object_key)
    return SuccessResponse(
        data=payload,
        message=(
            "Resume re-parsed"
            if resume.status == ResumeStatus.PARSED
            else f"Processing finished with status {resume.status.value}"
        ),
    )
