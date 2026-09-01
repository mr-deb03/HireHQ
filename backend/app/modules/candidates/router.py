"""Candidate management endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ApplicationStatus, DocumentType
from app.core.permissions import Perm
from app.core.responses import Page, SuccessResponse
from app.db.session import get_db
from app.dependencies.auth import CompanyScope, CurrentUser, require_permission
from app.models.candidate import CandidateDocument
from app.modules.candidates.schemas import (
    CandidateApplicationBrief,
    CandidateDetail,
    CandidateSummaryOut,
    CandidateSummaryResponse,
    CandidateUpdate,
    DocumentOut,
    EducationUpdate,
    ExperienceUpdate,
    GenerateSummaryRequest,
    NoteCreate,
    NoteOut,
    ResolveFlagRequest,
    SkillsUpdate,
)
from app.modules.candidates.service import CandidateService
from app.providers.scanning import ScanVerdict, get_scanner, validate_upload
from app.providers.storage import build_object_key, get_storage
from app.schemas.common import PaginationParams, pagination

router = APIRouter(prefix="/candidates", tags=["Candidates"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

ReadCandidates = Depends(require_permission(Perm.CANDIDATE_READ))
UpdateCandidates = Depends(require_permission(Perm.CANDIDATE_UPDATE))


@router.get(
    "",
    response_model=SuccessResponse[Page[CandidateSummaryOut]],
    summary="Search candidates",
    description=(
        "Full candidate search across the company's talent. Supports skill, experience, "
        "location, notice-period and ATS-score filters."
    ),
    dependencies=[ReadCandidates],
)
async def search_candidates(
    company_id: CompanyScope,
    session: DbSession,
    page_params: Annotated[PaginationParams, Depends(pagination)],
    q: Annotated[str | None, Query(description="Name, email, phone or title")] = None,
    skills: Annotated[list[str] | None, Query(description="All must match")] = None,
    min_experience: Annotated[float | None, Query(ge=0, le=60)] = None,
    max_experience: Annotated[float | None, Query(ge=0, le=60)] = None,
    location: str | None = None,
    min_ats_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    job_id: uuid.UUID | None = None,
    application_status: Annotated[list[ApplicationStatus] | None, Query()] = None,
    max_notice_period: Annotated[int | None, Query(ge=0, le=365)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    sort: str = "-created_at",
) -> SuccessResponse[Page[CandidateSummaryOut]]:
    service = CandidateService(session, company_id)
    candidates, total = await service.search(
        query=q,
        skills=skills,
        min_experience=min_experience,
        max_experience=max_experience,
        location=location,
        min_ats_score=min_ats_score,
        job_id=job_id,
        application_status=application_status,
        max_notice_period=max_notice_period,
        tags=tags,
        page=page_params.page,
        page_size=page_params.page_size,
        sort=sort,
    )
    return SuccessResponse(
        data=Page.build(
            [CandidateSummaryOut.model_validate(c) for c in candidates],
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        )
    )


@router.get(
    "/{candidate_id}",
    response_model=SuccessResponse[CandidateDetail],
    summary="Get a candidate profile",
    dependencies=[ReadCandidates],
)
async def get_candidate(
    candidate_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[CandidateDetail]:
    candidate = await CandidateService(session, company_id).get(candidate_id)
    return SuccessResponse(data=CandidateDetail.model_validate(candidate))


@router.patch(
    "/{candidate_id}",
    response_model=SuccessResponse[CandidateDetail],
    summary="Update a candidate profile",
    dependencies=[UpdateCandidates],
)
async def update_candidate(
    candidate_id: uuid.UUID,
    payload: CandidateUpdate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateDetail]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    await service.update_profile(
        candidate, changes=payload.model_dump(exclude_unset=True), actor_id=principal.id
    )
    candidate = await service.get(candidate_id)
    return SuccessResponse(
        data=CandidateDetail.model_validate(candidate), message="Candidate updated"
    )


@router.put(
    "/{candidate_id}/skills",
    response_model=SuccessResponse[CandidateDetail],
    summary="Replace a candidate's skills",
    dependencies=[UpdateCandidates],
)
async def update_skills(
    candidate_id: uuid.UUID,
    payload: SkillsUpdate,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateDetail]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    await service.replace_skills(candidate, [s.model_dump() for s in payload.skills])
    candidate = await service.get(candidate_id)
    return SuccessResponse(
        data=CandidateDetail.model_validate(candidate),
        message="Skills updated. Re-score affected applications to refresh ATS results.",
    )


@router.put(
    "/{candidate_id}/education",
    response_model=SuccessResponse[CandidateDetail],
    summary="Replace a candidate's education history",
    dependencies=[UpdateCandidates],
)
async def update_education(
    candidate_id: uuid.UUID,
    payload: EducationUpdate,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateDetail]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    await service.replace_education(candidate, [e.model_dump() for e in payload.education])
    candidate = await service.get(candidate_id)
    return SuccessResponse(
        data=CandidateDetail.model_validate(candidate), message="Education updated"
    )


@router.put(
    "/{candidate_id}/experience",
    response_model=SuccessResponse[CandidateDetail],
    summary="Replace a candidate's work history",
    description="Recomputes total experience, merging overlapping roles.",
    dependencies=[UpdateCandidates],
)
async def update_experience(
    candidate_id: uuid.UUID,
    payload: ExperienceUpdate,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateDetail]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    await service.replace_experience(candidate, [e.model_dump() for e in payload.experience])
    candidate = await service.get(candidate_id)
    return SuccessResponse(
        data=CandidateDetail.model_validate(candidate), message="Work history updated"
    )


# ---------------------------------------------------------------- applications
@router.get(
    "/{candidate_id}/applications",
    response_model=SuccessResponse[list[CandidateApplicationBrief]],
    summary="List a candidate's applications",
    dependencies=[ReadCandidates],
)
async def candidate_applications(
    candidate_id: uuid.UUID, company_id: CompanyScope, session: DbSession
) -> SuccessResponse[list[CandidateApplicationBrief]]:
    service = CandidateService(session, company_id)
    await service.get(candidate_id)
    applications = await service.applications_for(candidate_id)
    return SuccessResponse(
        data=[
            CandidateApplicationBrief(
                id=a.id,
                reference_code=a.reference_code,
                status=a.status.value,
                ats_score=float(a.ats_score) if a.ats_score is not None else None,
                ats_rank=a.ats_rank,
                created_at=a.created_at,
                job_id=a.job_id,
                job_title=a.job.title if a.job else None,
            )
            for a in applications
        ]
    )


# ----------------------------------------------------------------------- notes
@router.get(
    "/{candidate_id}/notes",
    response_model=SuccessResponse[list[NoteOut]],
    summary="List internal notes",
    description="Private notes are visible only to their author and company admins.",
    dependencies=[ReadCandidates],
)
async def list_notes(
    candidate_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[list[NoteOut]]:
    service = CandidateService(session, company_id)
    await service.get(candidate_id)
    notes = await service.list_notes(
        candidate_id,
        viewer_id=principal.id,
        can_see_private=principal.has(Perm.FEEDBACK_READ_PRIVATE),
    )
    return SuccessResponse(data=[NoteOut.model_validate(n) for n in notes])


@router.post(
    "/{candidate_id}/notes",
    response_model=SuccessResponse[NoteOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add an internal note",
    description="Notes are never visible to the candidate.",
    dependencies=[Depends(require_permission(Perm.CANDIDATE_NOTE_WRITE))],
)
async def add_note(
    candidate_id: uuid.UUID,
    payload: NoteCreate,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[NoteOut]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    note = await service.add_note(
        candidate,
        body=payload.body,
        author_id=principal.id,
        application_id=payload.application_id,
        is_private=payload.is_private,
    )
    return SuccessResponse(data=NoteOut.model_validate(note), message="Note added")


# ------------------------------------------------------------------ ai summary
@router.post(
    "/{candidate_id}/generate-summary",
    response_model=SuccessResponse[CandidateSummaryResponse],
    summary="Generate an AI profile summary",
    description=(
        "Produces a recruiter-facing summary grounded in the candidate's own profile "
        "data. Advisory only - it never makes a recommendation to hire or reject."
    ),
    dependencies=[Depends(require_permission(Perm.AI_GENERATE))],
)
async def generate_summary(
    candidate_id: uuid.UUID,
    payload: GenerateSummaryRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateSummaryResponse]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    summary, strengths, considerations, engine = await service.generate_summary(
        candidate, job_id=payload.job_id, actor_id=principal.id
    )
    return SuccessResponse(
        data=CandidateSummaryResponse(
            summary=summary,
            strengths=strengths,
            considerations=considerations,
            engine=engine,
            generated_at=datetime.now(UTC),
        )
    )


# ---------------------------------------------------------------------- flags
@router.post(
    "/{candidate_id}/resolve-flag",
    response_model=SuccessResponse[CandidateDetail],
    summary="Resolve a review flag",
    description=(
        "Marks a review signal as looked at by a human. Flags are prompts for review, "
        "never automatic judgements - only a person can clear one."
    ),
    dependencies=[UpdateCandidates],
)
async def resolve_flag(
    candidate_id: uuid.UUID,
    payload: ResolveFlagRequest,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[CandidateDetail]:
    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)
    await service.resolve_flag(candidate, payload.code, actor_id=principal.id)
    candidate = await service.get(candidate_id)
    return SuccessResponse(
        data=CandidateDetail.model_validate(candidate), message="Review flag resolved"
    )


# ------------------------------------------------------------------ documents
@router.get(
    "/{candidate_id}/documents",
    response_model=SuccessResponse[list[DocumentOut]],
    summary="List a candidate's documents",
    description="Each item carries a short-lived signed download URL.",
    dependencies=[Depends(require_permission(Perm.CANDIDATE_DOCUMENT_READ))],
)
async def list_documents(
    candidate_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
) -> SuccessResponse[list[DocumentOut]]:
    await CandidateService(session, company_id).get(candidate_id)

    stmt = select(CandidateDocument).where(
        CandidateDocument.candidate_id == candidate_id,
        CandidateDocument.company_id == company_id,
    )
    # Confidential documents (offer letters, ID proofs) need the onboarding permission.
    if not principal.has(Perm.ONBOARDING_MANAGE):
        stmt = stmt.where(CandidateDocument.is_confidential.is_(False))

    documents = list((await session.execute(stmt)).scalars().all())
    storage = get_storage()
    items: list[DocumentOut] = []
    for document in documents:
        payload = DocumentOut.model_validate(document)
        payload.download_url = await storage.signed_url(document.object_key)
        items.append(payload)
    return SuccessResponse(data=items)


@router.post(
    "/{candidate_id}/documents",
    response_model=SuccessResponse[DocumentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a candidate document",
    description="Validated, virus-scanned and stored privately. Never publicly reachable.",
    dependencies=[UpdateCandidates],
)
async def upload_document(
    candidate_id: uuid.UUID,
    principal: CurrentUser,
    company_id: CompanyScope,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    document_type: DocumentType = DocumentType.OTHER,
    is_confidential: bool = False,
) -> SuccessResponse[DocumentOut]:
    from app.core.config import settings
    from app.core.exceptions import MalwareDetected

    service = CandidateService(session, company_id)
    candidate = await service.get(candidate_id)

    content = await file.read()
    extension, content_type = validate_upload(
        filename=file.filename or "document",
        content=content,
        allowed_extensions={"pdf", "docx", "doc", "png", "jpg", "jpeg"},
        max_size_mb=settings.MAX_DOCUMENT_SIZE_MB,
    )

    scan = await get_scanner().scan(content, extension=extension)
    if scan.verdict in (ScanVerdict.INFECTED, ScanVerdict.ERROR):
        raise MalwareDetected(
            "This file was rejected by the security scan and has not been stored.",
            details={"findings": scan.findings, "verdict": scan.verdict.value},
        )

    storage = get_storage()
    object_key = build_object_key(
        company_id=company_id,
        category="documents",
        filename=file.filename or "document",
        entity_id=candidate.id,
    )
    stored = await storage.put(object_key, content, content_type=content_type)

    document = CandidateDocument(
        company_id=company_id,
        candidate_id=candidate.id,
        document_type=document_type,
        file_name=(file.filename or "document")[:255],
        object_key=stored.object_key,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        scan_status=scan.verdict.value,
        scan_detail=(scan.detail or "")[:255] or None,
        uploaded_by_id=principal.id,
        is_confidential=is_confidential,
    )
    session.add(document)
    await session.flush()

    payload = DocumentOut.model_validate(document)
    payload.download_url = await storage.signed_url(document.object_key)
    return SuccessResponse(data=payload, message="Document uploaded")
