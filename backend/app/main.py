"""HireHQ API application factory.

From Application to Hire - Automated.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.responses import ok
from app.db.bootstrap import bootstrap_database, ensure_schema
from app.db.session import dispose_engine, session_scope
from app.middleware.context import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.middleware.errors import register_exception_handlers
from app.providers.ai.factory import get_ai_provider
from app.providers.calendar import get_calendar_provider
from app.providers.email import get_email_provider
from app.providers.storage import get_storage
from app.services.subscribers import register_subscribers

logger = get_logger(__name__)

DESCRIPTION = """
**HireHQ** is an AI-assisted applicant tracking system, job portal and recruitment
automation platform.

### How to use these docs
1. `POST /api/v1/auth/login` with a seeded demo account.
2. Click **Authorize** and paste the `access_token`.
3. Every endpoint below is then callable with that identity's permissions.

### Response shape
Success: `{"success": true, "data": ..., "message": ...}`
Error:   `{"success": false, "error": {"code": ..., "message": ...}}`

### A note on AI and automation
AI features assist recruiters; they never decide. ATS scores are explainable and
configurable, automated workflows are auditable and reversible, and every AI-assisted
output is recorded with the engine that produced it. Integrations that are not
configured say so - the API never reports an email as sent, or a calendar invitation as
delivered, when it was not.
"""

TAGS_METADATA = [
    {"name": "Health", "description": "Liveness, readiness and provider status."},
    {"name": "Authentication", "description": "Registration, sign-in, tokens and profile."},
    {"name": "Users", "description": "Company user and hiring-team management."},
    {"name": "Companies", "description": "Company profile, departments and locations."},
    {"name": "Jobs", "description": "Job creation, publication and AI requirement analysis."},
    {"name": "Public", "description": "Unauthenticated job portal: search, browse and apply."},
    {"name": "Candidates", "description": "Candidate profiles, documents, notes and search."},
    {"name": "Applications", "description": "Applications, pipeline, Kanban and bulk actions."},
    {"name": "Resumes", "description": "Resume upload, parsing pipeline and extracted data."},
    {"name": "ATS", "description": "Explainable scoring, ranking and weight configuration."},
    {"name": "Screening", "description": "Screening questions, answers and automated rules."},
    {"name": "Assessments", "description": "Technical assessments, attempts and results."},
    {"name": "Interviews", "description": "Scheduling, rounds, participants and feedback."},
    {"name": "Calendar", "description": "Interview calendar views and provider integration."},
    {"name": "Emails", "description": "Templates, sending and the recruitment inbox."},
    {"name": "Notifications", "description": "Notification centre and preferences."},
    {"name": "Workflows", "description": "Trigger/condition/action automation engine."},
    {"name": "Offers", "description": "Offer drafting, approval, delivery and response."},
    {"name": "Onboarding", "description": "Preboarding, document collection and joining."},
    {"name": "Talent Pool", "description": "Reusable candidate pools and AI matching."},
    {"name": "Referrals", "description": "Employee referrals and referral analytics."},
    {"name": "Analytics", "description": "Funnel, source, conversion and time-to-hire metrics."},
    {"name": "AI", "description": "Recruiter assistant, summaries and AI governance."},
    {"name": "Files", "description": "Signed-URL download of private documents."},
    {"name": "Admin", "description": "Platform administration and audit logs."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info(
        "starting",
        app=settings.APP_NAME,
        env=settings.APP_ENV,
        database=settings.DATABASE_URL.split("://")[0],
    )

    await ensure_schema()
    async with session_scope() as session:
        await bootstrap_database(session)

    register_subscribers()

    # Resolve providers at boot so a misconfiguration surfaces here rather than on the
    # first candidate application at 2am.
    ai = get_ai_provider()
    storage = get_storage()
    email = get_email_provider()
    calendar = get_calendar_provider()
    app.state.providers = {
        "ai": {"name": ai.name, "real_model": ai.is_real_model},
        "storage": {"name": storage.name, "durable": storage.is_durable},
        "email": {"name": email.name, "transmits": email.transmits},
        "calendar": {"name": calendar.name, "delivers": calendar.delivers_invitations},
    }
    if not ai.is_real_model:
        logger.warning(
            "ai_running_without_model",
            detail="Using the deterministic heuristic engine. Set AI_PROVIDER=anthropic "
            "and AI_API_KEY for LLM-backed features.",
        )
    if not email.transmits:
        logger.warning(
            "email_not_transmitting",
            detail="Emails will be recorded but not delivered. Configure SMTP to send.",
        )

    logger.info("started", providers=app.state.providers)
    yield

    logger.info("shutting_down")
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        summary=settings.APP_TAGLINE,
        description=DESCRIPTION,
        version="1.0.0",
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
        contact={"name": "HireHQ", "url": settings.FRONTEND_BASE_URL},
        license_info={"name": "Proprietary"},
    )

    # Order matters: the outermost middleware runs first on the way in. Request context
    # must be established before anything that logs, and rate limiting must see the
    # authenticated principal that the router sets.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return ok(
            {
                "name": settings.APP_NAME,
                "tagline": settings.APP_TAGLINE,
                "version": "1.0.0",
                "docs": "/docs",
                "api": settings.API_V1_PREFIX,
            }
        )

    @app.get("/health", tags=["Health"], summary="Readiness probe")
    async def health() -> dict:
        """Reports database reachability and which providers are actually configured."""
        from sqlalchemy import text

        from app.db.session import SessionFactory

        database_ok = True
        try:
            async with SessionFactory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            database_ok = False
            logger.error("health_database_unreachable", error=str(exc))

        providers = getattr(app.state, "providers", {})
        return ok(
            {
                "status": "healthy" if database_ok else "degraded",
                "environment": settings.APP_ENV,
                "database": "up" if database_ok else "down",
                "providers": providers,
            }
        )

    @app.get("/health/live", tags=["Health"], summary="Liveness probe", include_in_schema=False)
    async def live() -> dict:
        return {"status": "alive"}

    return app


app = create_app()
