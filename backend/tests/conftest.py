"""Shared test fixtures.

Each test runs against its own throwaway SQLite database so tests never interfere with
one another or with a developer's local data. Configuration is forced into a known state
*before* application modules are imported, because ``Settings`` is cached at import time.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

# Must precede any `app.*` import: Settings is instantiated at module import.
TEST_DB = Path(__file__).parent / f"test_{uuid.uuid4().hex[:8]}.db"
os.environ.update(
    APP_ENV="test",
    DEBUG="false",
    DATABASE_URL=f"sqlite+aiosqlite:///{TEST_DB.as_posix()}",
    JWT_SECRET="test-secret-key-that-is-long-enough-for-tests-1234567890",
    STORAGE_PROVIDER="local",
    STORAGE_LOCAL_PATH=str(Path(__file__).parent / "_test_storage"),
    AI_PROVIDER="heuristic",
    EMAIL_PROVIDER="console",
    CALENDAR_PROVIDER="none",
    USE_REDIS_QUEUE="false",
    RATE_LIMIT_ENABLED="false",
    MALWARE_SCANNER="basic",
    SEED_DEMO_PASSWORD="TestPass!2024",
)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.enums import RoleName, UserStatus  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.bootstrap import bootstrap_database  # noqa: E402
from app.db.session import SessionFactory, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.user import Role, User  # noqa: E402

TEST_PASSWORD = "TestPass!2024"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionFactory() as session:
        await bootstrap_database(session)
        await session.commit()

    yield

    await engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(TEST_DB) + suffix)
        if path.exists():
            path.unlink()

    storage = Path(os.environ["STORAGE_LOCAL_PATH"])
    if storage.exists():
        import shutil

        shutil.rmtree(storage, ignore_errors=True)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionFactory() as db:
        yield db
        await db.rollback()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client bound to the ASGI app, bypassing the network."""
    from app.main import create_app
    from app.services.subscribers import register_subscribers

    register_subscribers()
    app = create_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30
    ) as http_client:
        yield http_client


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    from app.utils.text import slugify

    name = f"Acme {uuid.uuid4().hex[:6]}"
    record = Company(
        name=name,
        slug=slugify(name),
        industry="Technology",
        status="ACTIVE",
        contact_email="hr@acme.test",
    )
    session.add(record)
    await session.flush()

    from app.modules.ats.service import AtsService
    from app.modules.emails.service import EmailService

    await AtsService(session, record.id).ensure_default_profile()
    await EmailService(session, record.id).ensure_default_templates()
    await session.commit()
    return record


async def _make_user(
    session: AsyncSession,
    *,
    roles: list[RoleName],
    company_id: uuid.UUID | None,
    email: str | None = None,
    first_name: str = "Test",
    last_name: str = "User",
) -> User:
    from sqlalchemy import select

    email = email or f"{uuid.uuid4().hex[:10]}@hirehq.test"
    user = User(
        email=email,
        hashed_password=hash_password(TEST_PASSWORD),
        first_name=first_name,
        last_name=last_name,
        company_id=company_id,
        status=UserStatus.ACTIVE,
    )
    from datetime import UTC, datetime

    user.email_verified_at = datetime.now(UTC)

    for role_name in roles:
        role = await session.scalar(
            select(Role).where(Role.name == role_name.value, Role.company_id.is_(None))
        )
        user.roles.append(role)

    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def recruiter(session: AsyncSession, company: Company) -> User:
    return await _make_user(
        session,
        roles=[RoleName.COMPANY_ADMIN, RoleName.RECRUITER],
        company_id=company.id,
        first_name="Rita",
        last_name="Recruiter",
    )


@pytest.fixture
async def interviewer(session: AsyncSession, company: Company) -> User:
    return await _make_user(
        session,
        roles=[RoleName.INTERVIEWER],
        company_id=company.id,
        first_name="Ivan",
        last_name="Interviewer",
    )


@pytest.fixture
async def candidate_user(session: AsyncSession) -> User:
    return await _make_user(
        session,
        roles=[RoleName.CANDIDATE],
        company_id=None,
        first_name="Casey",
        last_name="Candidate",
    )


async def login(client: httpx.AsyncClient, email: str, password: str = TEST_PASSWORD) -> str:
    """Return an access token, failing loudly if authentication did not work."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["tokens"]["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def recruiter_token(client: httpx.AsyncClient, recruiter: User) -> str:
    return await login(client, recruiter.email)


@pytest.fixture
async def interviewer_token(client: httpx.AsyncClient, interviewer: User) -> str:
    return await login(client, interviewer.email)


def build_docx(text: str) -> bytes:
    """A real .docx, so upload/extraction tests exercise the genuine path."""
    from io import BytesIO

    import docx

    document = docx.Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


SAMPLE_RESUME = """Rahul Sharma
rahul.sharma@example.test
+91 9876543210
Bengaluru, India
https://linkedin.com/in/rahulsharma
https://github.com/rahulsharma

SUMMARY
Senior Frontend Engineer with 6 years of experience building production web
applications at scale.

SKILLS
React, TypeScript, JavaScript, REST API, Git, CSS, HTML, Next.js, Redux, Jest

EXPERIENCE
Senior Frontend Engineer at Flipkart    Mar 2022 - Present
- Built and maintained reusable React components for the seller design system
- Developed REST API integrations for the catalogue service
- Mentored three junior developers and led frontend code reviews

Frontend Engineer at Zoho    Mar 2020 - Mar 2022
- Developed customer-facing React and TypeScript interfaces
- Collaborated with design on a shared component library

EDUCATION
B.Tech in Computer Science from NIT Trichy    2016 - 2020
"""
