"""Integration tests for authentication, RBAC and tenant isolation."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.models.company import Company
from app.models.user import User
from tests.conftest import TEST_PASSWORD, auth, login


class TestRegistration:
    async def test_registers_a_candidate(self, client: httpx.AsyncClient):
        email = f"new_{uuid.uuid4().hex[:8]}@hirehq.test"
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPass!2024",
                "first_name": "New",
                "last_name": "Candidate",
                "accept_terms": True,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["success"] is True
        assert body["data"]["user"]["email"] == email

    async def test_reports_email_delivery_truthfully(self, client: httpx.AsyncClient):
        """With no provider configured the response must not imply an email was sent."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"x_{uuid.uuid4().hex[:8]}@hirehq.test",
                "password": "StrongPass!2024",
                "first_name": "A",
                "last_name": "B",
                "accept_terms": True,
            },
        )
        data = response.json()["data"]
        # The structured field is the honest signal, and it is what clients act on.
        assert data["verification_email_status"] == "NOT_SENT_NO_PROVIDER"
        # The prose must not send anyone to an inbox that will never receive anything.
        # What it says beyond that depends on whether verification is being enforced at
        # all, so assert the property rather than one particular sentence.
        message = data["message"].lower()
        assert "check your email" not in message, data["message"]
        assert "sent" not in message, data["message"]

    async def test_rejects_a_weak_password(self, client: httpx.AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"w_{uuid.uuid4().hex[:8]}@hirehq.test",
                "password": "weak",
                "first_name": "A",
                "last_name": "B",
                "accept_terms": True,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_requires_consent(self, client: httpx.AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"c_{uuid.uuid4().hex[:8]}@hirehq.test",
                "password": "StrongPass!2024",
                "first_name": "A",
                "last_name": "B",
                "accept_terms": False,
            },
        )
        assert response.status_code == 422

    async def test_duplicate_email_is_rejected(self, client: httpx.AsyncClient, recruiter):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": recruiter.email,
                "password": "StrongPass!2024",
                "first_name": "A",
                "last_name": "B",
                "accept_terms": True,
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


class TestLogin:
    async def test_successful_login_returns_tokens_and_permissions(
        self, client: httpx.AsyncClient, recruiter: User
    ):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": recruiter.email, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["tokens"]["access_token"]
        assert data["tokens"]["refresh_token"]
        assert "job:create" in data["user"]["permissions"]

    async def test_wrong_password_is_rejected(
        self, client: httpx.AsyncClient, recruiter: User
    ):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": recruiter.email, "password": "WrongPassword!1"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_unknown_account_gives_the_same_error(self, client: httpx.AsyncClient):
        """Identical response, so login cannot be used to enumerate accounts."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nowhere.test", "password": "WrongPassword!1"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_refresh_rotates_the_token(
        self, client: httpx.AsyncClient, recruiter: User
    ):
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": recruiter.email, "password": TEST_PASSWORD},
        )
        refresh_token = login_response.json()["data"]["tokens"]["refresh_token"]

        first = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert first.status_code == 200
        assert first.json()["data"]["refresh_token"] != refresh_token

        # Replaying the consumed token must fail and kill the session family.
        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert replay.status_code == 401


class TestAuthorisation:
    async def test_unauthenticated_request_is_rejected(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/jobs")
        assert response.status_code == 401
        assert response.json()["success"] is False

    async def test_garbage_token_is_rejected(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/jobs", headers=auth("not-a-real-token"))
        assert response.status_code == 401

    async def test_me_returns_the_signed_in_user(
        self, client: httpx.AsyncClient, recruiter_token: str, recruiter: User
    ):
        response = await client.get("/api/v1/auth/me", headers=auth(recruiter_token))
        assert response.status_code == 200
        assert response.json()["data"]["email"] == recruiter.email

    async def test_interviewer_cannot_create_a_job(
        self, client: httpx.AsyncClient, interviewer_token: str
    ):
        response = await client.post(
            "/api/v1/jobs",
            headers=auth(interviewer_token),
            json={
                "title": "Sneaky Job",
                "description": "x" * 200,
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    async def test_candidate_cannot_read_the_candidate_database(
        self, client: httpx.AsyncClient, candidate_user: User
    ):
        token = await login(client, candidate_user.email)
        response = await client.get("/api/v1/candidates", headers=auth(token))
        assert response.status_code == 403

    async def test_non_admin_cannot_reach_platform_admin(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.get("/api/v1/admin/stats", headers=auth(recruiter_token))
        assert response.status_code == 403


class TestTenantIsolation:
    async def test_a_company_cannot_read_another_companys_job(
        self, client: httpx.AsyncClient, session, recruiter: User, recruiter_token: str
    ):
        """The core multi-tenancy guarantee, exercised over HTTP."""
        from app.core.enums import RoleName
        from app.utils.text import slugify
        from tests.conftest import _make_user

        other = Company(name="Rival Corp", slug=slugify(f"rival-{uuid.uuid4().hex[:6]}"))
        session.add(other)
        await session.flush()

        from app.modules.ats.service import AtsService
        from app.modules.emails.service import EmailService

        await AtsService(session, other.id).ensure_default_profile()
        await EmailService(session, other.id).ensure_default_templates()
        rival = await _make_user(
            session, roles=[RoleName.RECRUITER], company_id=other.id
        )
        rival_token = await login(client, rival.email)

        created = await client.post(
            "/api/v1/jobs",
            headers=auth(rival_token),
            json={
                "title": "Rival Secret Role",
                "description": "A confidential role at a competitor. " * 10,
                "required_skills": [{"name": "Python"}],
            },
        )
        assert created.status_code == 201, created.text
        rival_job_id = created.json()["data"]["id"]

        # The first company must not be able to read it, and must get a 404 - not a 403,
        # which would confirm the resource exists.
        response = await client.get(
            f"/api/v1/jobs/{rival_job_id}", headers=auth(recruiter_token)
        )
        assert response.status_code == 404

        listing = await client.get("/api/v1/jobs", headers=auth(recruiter_token))
        titles = [j["title"] for j in listing.json()["data"]["items"]]
        assert "Rival Secret Role" not in titles

    async def test_tenant_repository_refuses_to_be_built_without_a_company(self, session):
        """Structural guarantee: a tenant query cannot be constructed unscoped."""
        from app.models.job import Job
        from app.repositories.base import TenantRepository

        class JobRepository(TenantRepository[Job]):
            model = Job

        with pytest.raises(ValueError, match="requires a company_id"):
            JobRepository(session, None)


class TestPasswordChange:
    async def test_change_password_invalidates_existing_sessions(
        self, client: httpx.AsyncClient, session, company
    ):
        from app.core.enums import RoleName
        from tests.conftest import _make_user

        user = await _make_user(
            session, roles=[RoleName.RECRUITER], company_id=company.id
        )
        token = await login(client, user.email)

        assert (await client.get("/api/v1/auth/me", headers=auth(token))).status_code == 200

        changed = await client.post(
            "/api/v1/auth/change-password",
            headers=auth(token),
            json={"current_password": TEST_PASSWORD, "password": "BrandNewPass!2024"},
        )
        assert changed.status_code == 200

        # The old access token must stop working immediately.
        stale = await client.get("/api/v1/auth/me", headers=auth(token))
        assert stale.status_code == 401

        # And the new password must work.
        await login(client, user.email, "BrandNewPass!2024")

    async def test_wrong_current_password_is_rejected(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.post(
            "/api/v1/auth/change-password",
            headers=auth(recruiter_token),
            json={"current_password": "NotMyPassword!1", "password": "BrandNewPass!2024"},
        )
        assert response.status_code == 401


class TestErrorEnvelope:
    async def test_errors_use_the_standard_shape(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/jobs")
        body = response.json()
        assert body["success"] is False
        assert "code" in body["error"] and "message" in body["error"]

    async def test_success_uses_the_standard_shape(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.get("/api/v1/jobs", headers=auth(recruiter_token))
        body = response.json()
        assert body["success"] is True
        assert "data" in body

    async def test_unknown_route_is_a_clean_404(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json()["success"] is False


class TestForgotPassword:
    async def test_response_does_not_reveal_whether_the_account_exists(
        self, client: httpx.AsyncClient, recruiter: User
    ):
        known = await client.post(
            "/api/v1/auth/forgot-password", json={"email": recruiter.email}
        )
        unknown = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "nobody@nowhere.test"}
        )
        assert known.status_code == unknown.status_code == 200
        assert known.json()["data"]["message"] == unknown.json()["data"]["message"]
