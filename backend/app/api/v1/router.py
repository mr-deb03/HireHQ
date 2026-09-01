"""Aggregates every v1 router under ``/api/v1``.

Order matters for a couple of prefixes: routers whose paths could shadow each other are
included so that the more specific one is registered first.
"""

from fastapi import APIRouter

from app.api.v1 import files, realtime
from app.modules.admin.router import router as admin_router
from app.modules.ai.router import router as ai_router
from app.modules.analytics.router import router as analytics_router
from app.modules.applications.router import router as applications_router
from app.modules.assessments.router import candidate_router as assessments_candidate_router
from app.modules.assessments.router import router as assessments_router
from app.modules.ats.router import router as ats_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.calendar.router import router as calendar_router
from app.modules.candidates.portal_router import router as candidate_portal_router
from app.modules.candidates.router import router as candidates_router
from app.modules.companies.router import router as companies_router
from app.modules.emails.accounts import router as email_accounts_router
from app.modules.emails.router import router as emails_router
from app.modules.interviews.router import router as interviews_router
from app.modules.jobs.public_router import router as public_router
from app.modules.jobs.router import router as jobs_router
from app.modules.notifications.router import router as notifications_router
from app.modules.offers.router import public_router as offers_public_router
from app.modules.offers.router import router as offers_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.referrals.router import internal_router as internal_jobs_router
from app.modules.referrals.router import router as referrals_router
from app.modules.resumes.router import router as resumes_router
from app.modules.talent_pool.router import router as talent_pool_router
from app.modules.users.router import router as users_router
from app.modules.workflows.router import router as workflows_router

api_router = APIRouter()

# ------------------------------------------------------------------ public
api_router.include_router(auth_router)
api_router.include_router(public_router)
api_router.include_router(files.router)

# Mailbox OAuth callback is unauthenticated: the provider redirects the browser here
# without our Authorization header, and the signed state proves identity instead.
api_router.include_router(email_accounts_router)

# Candidate-facing tokenised flows. Registered before the recruiter routers that share
# the same prefix so their concrete paths take precedence.
api_router.include_router(offers_public_router)
api_router.include_router(assessments_candidate_router)

# ---------------------------------------------------------- authenticated
api_router.include_router(candidate_portal_router)
api_router.include_router(companies_router)
api_router.include_router(users_router)
api_router.include_router(jobs_router)
api_router.include_router(candidates_router)
api_router.include_router(applications_router)
api_router.include_router(resumes_router)
api_router.include_router(ats_router)
api_router.include_router(assessments_router)
api_router.include_router(interviews_router)
api_router.include_router(calendar_router)
api_router.include_router(emails_router)
api_router.include_router(realtime.router)
api_router.include_router(notifications_router)
api_router.include_router(workflows_router)
api_router.include_router(offers_router)
api_router.include_router(onboarding_router)
api_router.include_router(talent_pool_router)
api_router.include_router(referrals_router)
api_router.include_router(internal_jobs_router)
api_router.include_router(analytics_router)
api_router.include_router(ai_router)

# ------------------------------------------------------------------- admin
api_router.include_router(admin_router)
api_router.include_router(audit_router)

__all__ = ["api_router"]
