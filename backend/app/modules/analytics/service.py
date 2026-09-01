"""Recruitment analytics: funnel, sources, conversion and time-to-hire.

Every figure is computed with SQL aggregates rather than by loading rows into Python, so
these endpoints stay fast on a company with hundreds of thousands of applications.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ApplicationStatus,
    InterviewStatus,
    JobStatus,
    OfferStatus,
)
from app.models.application import Application
from app.models.interview import Interview, InterviewFeedback
from app.models.job import Job
from app.models.offer import Offer
from app.modules.applications.state_machine import PIPELINE_ORDER, reached_stage


class AnalyticsService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID) -> None:
        self.session = session
        self.company_id = company_id

    # ------------------------------------------------------------- helpers
    def _scope(self, stmt: Select, *, since: date | None = None, until: date | None = None) -> Select:
        stmt = stmt.where(Application.company_id == self.company_id)
        if since:
            stmt = stmt.where(Application.created_at >= datetime.combine(since, datetime.min.time(), tzinfo=UTC))
        if until:
            stmt = stmt.where(Application.created_at < datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC))
        return stmt

    async def _status_counts(
        self, *, job_id: uuid.UUID | None = None, since: date | None = None, until: date | None = None
    ) -> dict[str, int]:
        stmt = self._scope(
            select(Application.status, func.count()).group_by(Application.status),
            since=since,
            until=until,
        )
        if job_id:
            stmt = stmt.where(Application.job_id == job_id)
        return {row[0].value: row[1] for row in (await self.session.execute(stmt)).all()}

    # ----------------------------------------------------------- dashboard
    async def dashboard_kpis(self, *, recruiter_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Headline numbers for the recruiter dashboard (s38)."""
        now = datetime.now(UTC)
        week_ago = now - timedelta(days=7)

        active_jobs = (
            await self.session.execute(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.company_id == self.company_id,
                    Job.status == JobStatus.PUBLISHED,
                    Job.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        base = select(func.count()).select_from(Application).where(
            Application.company_id == self.company_id
        )
        if recruiter_id:
            base = base.where(Application.assigned_recruiter_id == recruiter_id)

        total_applications = (await self.session.execute(base)).scalar_one()
        new_this_week = (
            await self.session.execute(base.where(Application.created_at >= week_ago))
        ).scalar_one()
        shortlisted = (
            await self.session.execute(
                base.where(Application.status == ApplicationStatus.SHORTLISTED)
            )
        ).scalar_one()
        pending_review = (
            await self.session.execute(
                base.where(
                    Application.status.in_(
                        [ApplicationStatus.APPLIED, ApplicationStatus.UNDER_REVIEW]
                    )
                )
            )
        ).scalar_one()
        hired = (
            await self.session.execute(
                base.where(Application.status == ApplicationStatus.HIRED)
            )
        ).scalar_one()

        interviews_today = (
            await self.session.execute(
                select(func.count())
                .select_from(Interview)
                .where(
                    Interview.company_id == self.company_id,
                    Interview.scheduled_start >= now.replace(hour=0, minute=0, second=0, microsecond=0),
                    Interview.scheduled_start < now.replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=1),
                    Interview.status.in_(
                        [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                    ),
                )
            )
        ).scalar_one()

        upcoming_interviews = (
            await self.session.execute(
                select(func.count())
                .select_from(Interview)
                .where(
                    Interview.company_id == self.company_id,
                    Interview.scheduled_start >= now,
                    Interview.status.in_(
                        [InterviewStatus.SCHEDULED, InterviewStatus.CONFIRMED]
                    ),
                )
            )
        ).scalar_one()

        # Completed interviews with no submitted feedback.
        pending_feedback = (
            await self.session.execute(
                select(func.count())
                .select_from(Interview)
                .outerjoin(
                    InterviewFeedback,
                    and_(
                        InterviewFeedback.interview_id == Interview.id,
                        InterviewFeedback.is_draft.is_(False),
                    ),
                )
                .where(
                    Interview.company_id == self.company_id,
                    Interview.status == InterviewStatus.COMPLETED,
                    InterviewFeedback.id.is_(None),
                )
            )
        ).scalar_one()

        offers_pending = (
            await self.session.execute(
                select(func.count())
                .select_from(Offer)
                .where(
                    Offer.company_id == self.company_id,
                    Offer.status.in_([OfferStatus.SENT, OfferStatus.VIEWED]),
                )
            )
        ).scalar_one()

        strong_matches = (
            await self.session.execute(
                base.where(
                    Application.ats_score >= 85,
                    Application.status.in_(
                        [ApplicationStatus.APPLIED, ApplicationStatus.UNDER_REVIEW]
                    ),
                )
            )
        ).scalar_one()

        return {
            "active_jobs": active_jobs,
            "total_applications": total_applications,
            "new_applications_this_week": new_this_week,
            "shortlisted": shortlisted,
            "pending_review": pending_review,
            "strong_matches_awaiting_review": strong_matches,
            "interviews_today": interviews_today,
            "upcoming_interviews": upcoming_interviews,
            "pending_feedback": pending_feedback,
            "offers_awaiting_response": offers_pending,
            "hired": hired,
        }

    async def funnel(
        self,
        *,
        job_id: uuid.UUID | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> dict[str, Any]:
        """Cumulative recruitment funnel with stage-to-stage conversion."""
        counts = await self._status_counts(job_id=job_id, since=since, until=until)

        stages: list[dict[str, Any]] = []
        previous: int | None = None
        for stage in PIPELINE_ORDER:
            total = 0
            for status_value, count in counts.items():
                try:
                    status = ApplicationStatus(status_value)
                except ValueError:
                    continue
                if reached_stage(status, stage):
                    total += count
            conversion = (
                round(total / previous * 100, 1) if previous not in (None, 0) else None
            )
            stages.append(
                {
                    "stage": stage.value,
                    "label": stage.value.replace("_", " ").title(),
                    "count": total,
                    "conversion_from_previous_pct": conversion,
                }
            )
            previous = total

        applied = stages[0]["count"] if stages else 0
        hired = stages[-1]["count"] if stages else 0
        return {
            "stages": stages,
            "total_applications": applied,
            "total_hired": hired,
            "overall_conversion_pct": (
                round(hired / applied * 100, 2) if applied else 0.0
            ),
            "by_status": counts,
        }

    async def source_performance(
        self, *, since: date | None = None, until: date | None = None
    ) -> list[dict[str, Any]]:
        """Applications, shortlists, interviews and hires per source (s40).

        One grouped query with conditional aggregates rather than four round trips.
        """
        # Counted from the stage timestamps rather than the current status: an
        # application that reached interview and was later rejected must still count as
        # having been interviewed, or source performance understates every channel.
        stmt = self._scope(
            select(
                Application.source,
                func.count().label("applications"),
                func.sum(
                    case((Application.shortlisted_at.is_not(None), 1), else_=0)
                ).label("shortlisted"),
                func.sum(
                    case((Application.interviewed_at.is_not(None), 1), else_=0)
                ).label("interviewed"),
                func.sum(case((Application.offered_at.is_not(None), 1), else_=0)).label(
                    "offers"
                ),
                func.sum(case((Application.hired_at.is_not(None), 1), else_=0)).label(
                    "hired"
                ),
                func.avg(Application.ats_score).label("avg_score"),
            ).group_by(Application.source),
            since=since,
            until=until,
        )

        rows = (await self.session.execute(stmt)).all()
        results: list[dict[str, Any]] = []
        for row in rows:
            applications = row.applications or 0
            hired = int(row.hired or 0)
            results.append(
                {
                    "source": row.source.value,
                    "label": row.source.value.replace("_", " ").title(),
                    "applications": applications,
                    "shortlisted": int(row.shortlisted or 0),
                    "interviewed": int(row.interviewed or 0),
                    "offers": int(row.offers or 0),
                    "hired": hired,
                    "average_ats_score": (
                        round(float(row.avg_score), 1) if row.avg_score is not None else None
                    ),
                    "hire_rate_pct": (
                        round(hired / applications * 100, 2) if applications else 0.0
                    ),
                }
            )
        results.sort(key=lambda r: r["applications"], reverse=True)
        return results

    async def ats_distribution(
        self, *, job_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """Histogram of ATS scores in ten-point bands."""
        bands = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
        results = []
        for low, high in bands:
            stmt = select(func.count()).select_from(Application).where(
                Application.company_id == self.company_id,
                Application.ats_score >= low,
                Application.ats_score < high,
            )
            if job_id:
                stmt = stmt.where(Application.job_id == job_id)
            count = (await self.session.execute(stmt)).scalar_one()
            results.append(
                {
                    "band": f"{low}-{min(high, 100)}",
                    "min": low,
                    "max": min(high, 100),
                    "count": count,
                }
            )
        return results

    async def time_to_hire(self, *, job_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Average days from application to hire, and time spent in each stage."""
        stmt = select(
            Application.created_at,
            Application.shortlisted_at,
            Application.interviewed_at,
            Application.offered_at,
            Application.hired_at,
        ).where(
            Application.company_id == self.company_id,
            Application.hired_at.is_not(None),
        )
        if job_id:
            stmt = stmt.where(Application.job_id == job_id)

        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return {
                "hires_measured": 0,
                "average_days_to_hire": None,
                "median_days_to_hire": None,
                "stage_durations_days": {},
                "note": "No completed hires yet, so time-to-hire cannot be computed.",
            }

        totals: list[float] = []
        stage_totals: dict[str, list[float]] = {
            "application_to_shortlist": [],
            "shortlist_to_interview": [],
            "interview_to_offer": [],
            "offer_to_hire": [],
        }

        for created, shortlisted, interviewed, offered, hired in rows:
            totals.append((hired - created).total_seconds() / 86400)
            if shortlisted:
                stage_totals["application_to_shortlist"].append(
                    (shortlisted - created).total_seconds() / 86400
                )
                if interviewed:
                    stage_totals["shortlist_to_interview"].append(
                        (interviewed - shortlisted).total_seconds() / 86400
                    )
            if interviewed and offered:
                stage_totals["interview_to_offer"].append(
                    (offered - interviewed).total_seconds() / 86400
                )
            if offered:
                stage_totals["offer_to_hire"].append(
                    (hired - offered).total_seconds() / 86400
                )

        ordered = sorted(totals)
        median = (
            ordered[len(ordered) // 2]
            if len(ordered) % 2
            else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
        )

        return {
            "hires_measured": len(totals),
            "average_days_to_hire": round(sum(totals) / len(totals), 1),
            "median_days_to_hire": round(median, 1),
            "fastest_days": round(min(totals), 1),
            "slowest_days": round(max(totals), 1),
            "stage_durations_days": {
                key: round(sum(values) / len(values), 1)
                for key, values in stage_totals.items()
                if values
            },
        }

    async def job_performance(self, *, limit: int = 20) -> dict[str, Any]:
        """Jobs ranked by application volume, with their conversion figures."""
        stmt = (
            select(
                Job.id,
                Job.title,
                Job.reference_code,
                Job.status,
                Job.application_count,
                func.count(Application.id).label("applications"),
                func.sum(case((Application.shortlisted_at.is_not(None), 1), else_=0)).label(
                    "shortlisted"
                ),
                func.sum(case((Application.interviewed_at.is_not(None), 1), else_=0)).label(
                    "interviewed"
                ),
                func.sum(case((Application.hired_at.is_not(None), 1), else_=0)).label("hired"),
                func.avg(Application.ats_score).label("avg_score"),
            )
            .outerjoin(Application, Application.job_id == Job.id)
            .where(Job.company_id == self.company_id, Job.deleted_at.is_(None))
            .group_by(Job.id, Job.title, Job.reference_code, Job.status, Job.application_count)
            .order_by(func.count(Application.id).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        jobs = [
            {
                "job_id": str(row.id),
                "title": row.title,
                "reference_code": row.reference_code,
                "status": row.status.value,
                "applications": int(row.applications or 0),
                "shortlisted": int(row.shortlisted or 0),
                "interviewed": int(row.interviewed or 0),
                "hired": int(row.hired or 0),
                "average_ats_score": (
                    round(float(row.avg_score), 1) if row.avg_score is not None else None
                ),
                "interview_conversion_pct": (
                    round(int(row.interviewed or 0) / int(row.applications) * 100, 1)
                    if row.applications
                    else 0.0
                ),
            }
            for row in rows
        ]
        return {
            "highest_volume": jobs[:10],
            "lowest_volume": sorted(jobs, key=lambda j: j["applications"])[:10],
            "best_interview_conversion": sorted(
                [j for j in jobs if j["applications"] >= 3],
                key=lambda j: j["interview_conversion_pct"],
                reverse=True,
            )[:10],
        }

    async def recruiter_performance(self) -> list[dict[str, Any]]:
        from app.models.user import User

        stmt = (
            select(
                User.id,
                User.first_name,
                User.last_name,
                func.count(Application.id).label("assigned"),
                func.sum(case((Application.shortlisted_at.is_not(None), 1), else_=0)).label(
                    "shortlisted"
                ),
                func.sum(case((Application.hired_at.is_not(None), 1), else_=0)).label("hired"),
            )
            .join(Application, Application.assigned_recruiter_id == User.id)
            .where(Application.company_id == self.company_id)
            .group_by(User.id, User.first_name, User.last_name)
            .order_by(func.count(Application.id).desc())
        )
        return [
            {
                "recruiter_id": str(row.id),
                "name": f"{row.first_name} {row.last_name}",
                "applications_assigned": int(row.assigned or 0),
                "shortlisted": int(row.shortlisted or 0),
                "hired": int(row.hired or 0),
            }
            for row in (await self.session.execute(stmt)).all()
        ]

    async def drop_off(self) -> list[dict[str, Any]]:
        """Where candidates leave the process, so a recruiter can see the leaks."""
        rejected = (
            await self.session.execute(
                select(Application.status, func.count())
                .where(
                    Application.company_id == self.company_id,
                    Application.status.in_(
                        [
                            ApplicationStatus.REJECTED,
                            ApplicationStatus.WITHDRAWN,
                            ApplicationStatus.OFFER_REJECTED,
                            ApplicationStatus.INTERVIEW_FAILED,
                        ]
                    ),
                )
                .group_by(Application.status)
            )
        ).all()

        return [
            {
                "status": row[0].value,
                "label": row[0].value.replace("_", " ").title(),
                "count": row[1],
            }
            for row in rejected
        ]

    async def applications_over_time(self, *, days: int = 30) -> list[dict[str, Any]]:
        """Daily application volume for a trend chart."""
        since = datetime.now(UTC) - timedelta(days=days)
        rows = (
            await self.session.execute(
                select(
                    func.date(Application.created_at).label("day"),
                    func.count().label("count"),
                )
                .where(
                    Application.company_id == self.company_id,
                    Application.created_at >= since,
                )
                .group_by(func.date(Application.created_at))
                .order_by(func.date(Application.created_at))
            )
        ).all()
        return [{"date": str(row.day), "applications": row.count} for row in rows]

    async def attention_required(self) -> list[dict[str, Any]]:
        """The dashboard's "needs your attention" list (s38)."""
        kpis = await self.dashboard_kpis()
        items = [
            {
                "key": "new_applications",
                "count": kpis["pending_review"],
                "label": "applications need review",
                "url": "/recruiter/pipeline",
                "priority": "high" if kpis["pending_review"] > 20 else "normal",
            },
            {
                "key": "strong_matches",
                "count": kpis["strong_matches_awaiting_review"],
                "label": "strong matches awaiting review",
                "url": "/recruiter/pipeline?min_ats_score=85",
                "priority": "high",
            },
            {
                "key": "pending_feedback",
                "count": kpis["pending_feedback"],
                "label": "interview feedback forms pending",
                "url": "/recruiter/interviews?pending_feedback=true",
                "priority": "high" if kpis["pending_feedback"] > 3 else "normal",
            },
            {
                "key": "interviews_today",
                "count": kpis["interviews_today"],
                "label": "interviews scheduled today",
                "url": "/recruiter/calendar",
                "priority": "normal",
            },
            {
                "key": "offers_awaiting",
                "count": kpis["offers_awaiting_response"],
                "label": "offers awaiting a response",
                "url": "/recruiter/offers",
                "priority": "normal",
            },
        ]
        return [item for item in items if item["count"] > 0]
