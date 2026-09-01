"""Resume upload and the processing pipeline.

    Upload -> validate -> scan -> store -> extract text -> parse -> merge into profile
    -> ATS score

Upload is synchronous only as far as validating, scanning and storing the file (so the
candidate gets an immediate, honest yes/no). Everything after that runs as a background
job, because parsing a 40-page PDF and scoring it must not sit inside an HTTP request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import ResumeStatus, ReviewFlag
from app.core.exceptions import MalwareDetected, ResourceNotFound
from app.core.logging import get_logger
from app.models.candidate import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
)
from app.models.resume import Resume, ResumeAnalysis
from app.modules.resumes.extraction import extract_text
from app.providers.ai.base import AIProvider
from app.providers.ai.factory import get_ai_provider
from app.providers.ai.schemas import ParsedResume
from app.providers.scanning import ScanVerdict, get_scanner, validate_upload
from app.providers.storage import build_object_key, get_storage
from app.services.audit import AuditService
from app.utils.skills import categorise_skill, display_skill, normalise_skill
from app.utils.text import truncate

logger = get_logger(__name__)

#: Below this parse confidence the candidate is flagged for human review rather than
#: having low-quality extracted data silently trusted.
LOW_CONFIDENCE_THRESHOLD = 0.45


class ResumeService:
    def __init__(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
        *,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.session = session
        self.company_id = company_id
        self.ai = ai_provider or get_ai_provider()
        self.audit = AuditService(session)

    # ---------------------------------------------------------------- upload
    async def upload(
        self,
        *,
        candidate: Candidate,
        filename: str,
        content: bytes,
        uploaded_by_id: uuid.UUID | None = None,
        make_primary: bool = True,
    ) -> Resume:
        """Validate, scan and store a resume. Raises rather than storing anything unsafe."""
        extension, content_type = validate_upload(
            filename=filename,
            content=content,
            allowed_extensions=settings.allowed_resume_extensions,
            max_size_mb=settings.MAX_RESUME_SIZE_MB,
        )

        scanner = get_scanner()
        scan = await scanner.scan(content, extension=extension)
        if scan.verdict == ScanVerdict.INFECTED:
            logger.warning("resume_rejected_malware", findings=scan.findings)
            raise MalwareDetected(
                "This file was rejected by the security scan and has not been stored.",
                details={"findings": scan.findings},
            )
        if scan.verdict == ScanVerdict.ERROR:
            raise MalwareDetected(
                "The security scanner is unavailable, so this file cannot be accepted "
                "right now. Please try again shortly.",
                code="SCANNER_UNAVAILABLE",
            )

        storage = get_storage()
        object_key = build_object_key(
            company_id=self.company_id,
            category="resumes",
            filename=filename,
            entity_id=candidate.id,
        )
        stored = await storage.put(object_key, content, content_type=content_type)

        # Exact-duplicate detection: same bytes already on file for this company.
        duplicate = await self.session.scalar(
            select(Resume).where(
                Resume.company_id == self.company_id,
                Resume.checksum_sha256 == stored.checksum_sha256,
                Resume.candidate_id != candidate.id,
            )
        )

        if make_primary:
            for previous in await self._candidate_resumes(candidate.id):
                previous.is_primary = False

        resume = Resume(
            company_id=self.company_id,
            candidate_id=candidate.id,
            file_name=truncate(filename, 255),
            object_key=stored.object_key,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            status=ResumeStatus.UPLOADED,
            scan_status=scan.verdict.value,
            scan_engine=scan.engine,
            scan_detail=truncate(scan.detail, 255) if scan.detail else None,
            is_primary=make_primary,
        )
        self.session.add(resume)
        await self.session.flush()

        if scan.verdict == ScanVerdict.SUSPICIOUS:
            _add_flag(
                candidate,
                ReviewFlag.RESUME_PARSE_LOW_CONFIDENCE,
                f"The uploaded resume raised security warnings: {scan.detail}",
            )
        if duplicate is not None:
            _add_flag(
                candidate,
                ReviewFlag.DUPLICATE_RESUME_DETECTED,
                "This exact resume file has already been submitted by another candidate "
                "record in this company.",
            )

        logger.info(
            "resume_uploaded",
            resume_id=str(resume.id),
            size_bytes=stored.size_bytes,
            scan=scan.verdict.value,
        )
        return resume

    async def _candidate_resumes(self, candidate_id: uuid.UUID) -> list[Resume]:
        result = await self.session.execute(
            select(Resume).where(
                Resume.candidate_id == candidate_id, Resume.company_id == self.company_id
            )
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------ processing
    async def process(self, resume_id: uuid.UUID) -> Resume:
        """Extract, parse and merge. Idempotent: safe to retry after a failure."""
        resume = await self.session.scalar(
            select(Resume)
            .where(Resume.id == resume_id, Resume.company_id == self.company_id)
            .options(selectinload(Resume.analysis))
        )
        if resume is None:
            raise ResourceNotFound("Resume", resume_id)

        candidate = await self.session.scalar(
            select(Candidate)
            .where(Candidate.id == resume.candidate_id)
            .options(
                selectinload(Candidate.skills),
                selectinload(Candidate.education),
                selectinload(Candidate.experience),
            )
        )
        if candidate is None:
            raise ResourceNotFound("Candidate", resume.candidate_id)

        resume.processing_started_at = datetime.now(UTC)
        resume.processing_attempts += 1
        resume.status = ResumeStatus.EXTRACTING
        await self.session.flush()

        try:
            storage = get_storage()
            content = await storage.get(resume.object_key)
            extension = resume.file_name.rsplit(".", 1)[-1].lower()
            extraction = await extract_text(content, extension)

            resume.extracted_text = extraction.text
            resume.page_count = extraction.page_count
            resume.word_count = extraction.word_count

            if not extraction.is_usable:
                resume.status = ResumeStatus.FAILED
                resume.status_detail = (
                    "; ".join(extraction.warnings)
                    or "Not enough text could be extracted from this document."
                )
                resume.processing_completed_at = datetime.now(UTC)
                _add_flag(
                    candidate,
                    ReviewFlag.RESUME_PARSE_LOW_CONFIDENCE,
                    resume.status_detail,
                )
                logger.warning("resume_extraction_unusable", resume_id=str(resume.id))
                return resume

            resume.status = ResumeStatus.PARSING
            await self.session.flush()

            result = await self.ai.parse_resume(
                text=extraction.text, hint_name=candidate.full_name
            )
            parsed: ParsedResume = result.value

            await self._store_analysis(resume, parsed, engine=result.usage.engine)
            await self.merge_into_candidate(candidate, parsed, resume=resume)

            await self.audit.record_ai(
                feature="RESUME_PARSE",
                engine=result.usage.engine,
                model=result.usage.model,
                company_id=self.company_id,
                entity_type="Resume",
                entity_id=resume.id,
                input_digest={
                    "word_count": extraction.word_count,
                    "page_count": extraction.page_count,
                },
                output_summary={
                    "skills": len(parsed.skills),
                    "experience_entries": len(parsed.experience),
                    "education_entries": len(parsed.education),
                    "missing_fields": parsed.missing_fields,
                },
                confidence=parsed.confidence,
                latency_ms=result.usage.latency_ms,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                error=result.usage.error,
            )

            resume.status = ResumeStatus.PARSED
            resume.status_detail = None
            resume.processing_completed_at = datetime.now(UTC)

            if parsed.confidence < LOW_CONFIDENCE_THRESHOLD:
                _add_flag(
                    candidate,
                    ReviewFlag.RESUME_PARSE_LOW_CONFIDENCE,
                    f"The resume parsed with low confidence ({parsed.confidence:.0%}). "
                    "Please check the extracted details.",
                )
            self._check_employment_consistency(candidate, parsed)

            logger.info(
                "resume_parsed",
                resume_id=str(resume.id),
                engine=result.usage.engine,
                confidence=parsed.confidence,
                skills=len(parsed.skills),
            )
            return resume

        except Exception as exc:
            resume.status = ResumeStatus.FAILED
            resume.status_detail = truncate(str(exc), 500)
            resume.processing_completed_at = datetime.now(UTC)
            logger.error(
                "resume_processing_failed",
                resume_id=str(resume.id),
                error=str(exc),
                exc_info=True,
            )
            raise

    async def _store_analysis(
        self, resume: Resume, parsed: ParsedResume, *, engine: str
    ) -> ResumeAnalysis:
        analysis = resume.analysis
        if analysis is None:
            analysis = ResumeAnalysis(company_id=self.company_id, resume_id=resume.id)
            self.session.add(analysis)

        analysis.parsed_name = parsed.name
        analysis.parsed_email = parsed.email
        analysis.parsed_phone = parsed.phone
        analysis.parsed_location = parsed.location
        analysis.parsed_linkedin = parsed.linkedin_url
        analysis.parsed_github = parsed.github_url
        analysis.parsed_portfolio = parsed.portfolio_url
        analysis.skills = parsed.skills
        analysis.experience = [e.model_dump() for e in parsed.experience]
        analysis.education = [e.model_dump() for e in parsed.education]
        analysis.certifications = parsed.certifications
        analysis.projects = parsed.projects
        analysis.achievements = parsed.achievements
        analysis.languages = parsed.languages
        analysis.total_experience_years = parsed.total_experience_years
        analysis.current_designation = parsed.current_designation
        analysis.current_company = parsed.current_company
        analysis.summary = parsed.summary
        analysis.confidence = parsed.confidence
        analysis.parser_engine = engine
        analysis.missing_fields = parsed.missing_fields
        analysis.warnings = parsed.warnings
        await self.session.flush()
        return analysis

    # ---------------------------------------------------------------- merge
    async def merge_into_candidate(
        self, candidate: Candidate, parsed: ParsedResume, *, resume: Resume | None = None
    ) -> Candidate:
        """Fold parsed data into the candidate profile.

        Recruiter- and candidate-entered values always win: parsing fills gaps, it never
        overwrites something a human typed. Skills are merged by normalised name so
        "React" and "ReactJS" do not both end up on the profile.
        """
        if parsed.location and not candidate.location:
            candidate.location = parsed.location
        if parsed.phone and not candidate.phone:
            candidate.phone = parsed.phone
        if parsed.linkedin_url and not candidate.linkedin_url:
            candidate.linkedin_url = parsed.linkedin_url
        if parsed.github_url and not candidate.github_url:
            candidate.github_url = parsed.github_url
        if parsed.portfolio_url and not candidate.portfolio_url:
            candidate.portfolio_url = parsed.portfolio_url
        if parsed.summary and not candidate.summary:
            candidate.summary = truncate(parsed.summary, 2000)
        if parsed.current_designation and not candidate.current_designation:
            candidate.current_designation = truncate(parsed.current_designation, 200)
        if parsed.current_company and not candidate.current_company:
            candidate.current_company = truncate(parsed.current_company, 200)
        if parsed.total_experience_years and not candidate.total_experience_years:
            candidate.total_experience_years = parsed.total_experience_years

        existing_skills = {normalise_skill(s.normalised_name) for s in candidate.skills}
        for raw in parsed.skills[:80]:
            key = normalise_skill(raw)
            if not key or key in existing_skills:
                continue
            existing_skills.add(key)
            self.session.add(
                CandidateSkill(
                    candidate_id=candidate.id,
                    name=display_skill(raw),
                    normalised_name=key,
                    category=categorise_skill(raw),
                    source="RESUME",
                )
            )

        # Only import history when the profile has none, so a re-parse cannot duplicate
        # entries a candidate has already curated.
        if not candidate.experience:
            for entry in parsed.experience[:15]:
                self.session.add(
                    CandidateExperience(
                        candidate_id=candidate.id,
                        company_name=truncate(entry.company or "Unknown", 255),
                        position=truncate(entry.position or "Unknown", 200),
                        location=entry.location,
                        start_date=_to_date(entry.start_date),
                        end_date=_to_date(entry.end_date),
                        is_current=entry.is_current,
                        responsibilities=entry.responsibilities[:20],
                        technologies=entry.technologies[:20],
                        source="RESUME",
                    )
                )

        if not candidate.education:
            for entry in parsed.education[:10]:
                self.session.add(
                    CandidateEducation(
                        candidate_id=candidate.id,
                        degree=truncate(entry.degree or "Unknown", 200),
                        degree_level=entry.degree_level,
                        field_of_study=entry.field_of_study,
                        institution=entry.institution,
                        university=entry.university,
                        start_year=entry.start_year,
                        end_year=entry.end_year,
                        grade=entry.grade,
                        source="RESUME",
                    )
                )

        await self.session.flush()
        return candidate

    @staticmethod
    def _check_employment_consistency(candidate: Candidate, parsed: ParsedResume) -> None:
        """Raise a review flag on date problems - for a human to look at, never a verdict.

        Overlaps and gaps are extremely common and entirely legitimate (contracting,
        study, caring responsibilities, illness). The flag says "worth asking about", and
        the wording in the UI reflects that.
        """
        dated = [
            (e.start_date, e.end_date)
            for e in parsed.experience
            if e.start_date
        ]
        if len(dated) < 2:
            return

        inconsistent = False
        for start, end in dated:
            start_date, end_date = _to_date(start), _to_date(end)
            if start_date and end_date and end_date < start_date:
                inconsistent = True
                break

        if inconsistent:
            _add_flag(
                candidate,
                ReviewFlag.INCONSISTENT_EMPLOYMENT_DATES,
                "One or more roles have an end date before their start date. This is "
                "usually a formatting issue in the resume - worth confirming with the "
                "candidate.",
            )


def _add_flag(candidate: Candidate, flag: ReviewFlag, message: str) -> None:
    flags = list(candidate.review_flags or [])
    if any(f.get("code") == flag.value and not f.get("resolved") for f in flags):
        return
    flags.append(
        {
            "code": flag.value,
            "message": message,
            "raised_at": datetime.now(UTC).isoformat(),
            "resolved": False,
        }
    )
    candidate.review_flags = flags


def _to_date(value: str | None) -> Any:
    """Parse the loose date strings a parser may emit (``2021``, ``2021-03``, full ISO)."""
    if not value:
        return None
    from datetime import date

    text = str(value).strip()
    for fmt, builder in (
        ("%Y-%m-%d", lambda d: d),
        ("%Y-%m", lambda d: d.replace(day=1)),
        ("%Y", lambda d: d.replace(month=1, day=1)),
    ):
        try:
            return builder(datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
