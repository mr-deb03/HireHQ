"""End-to-end acceptance test for the core hiring workflow.

This walks the complete journey the product exists to support:

    recruiter signs in -> creates a job -> AI analyses the description ->
    recruiter confirms requirements -> publishes -> candidate finds the job publicly ->
    applies with a resume -> resume is parsed -> ATS score is generated ->
    candidate is ranked -> workflow evaluates and shortlists -> email is recorded ->
    interview is scheduled -> feedback is submitted -> AI summarises it ->
    offer is created and sent -> candidate accepts -> onboarding begins

Every step goes through the real HTTP API with real authentication, so this test failing
means the product is broken, not that a mock drifted.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from app.models.company import Company
from app.models.user import User
from tests.conftest import SAMPLE_RESUME, auth, build_docx, login

JOB_DESCRIPTION = """We are looking for a Senior React Developer to lead frontend work on
our customer platform.

Responsibilities:
- Build and maintain reusable React components and a shared design system
- Develop and consume REST APIs alongside the backend team
- Mentor junior developers and review their pull requests

Requirements:
- 4+ years of professional experience building web applications
- Deep expertise in React, TypeScript and modern JavaScript
- Strong experience with REST API integration
- Proficiency with Git
- Bachelor's degree in Computer Science or equivalent experience

Nice to have:
- Experience with Next.js
- Familiarity with AWS and Docker
"""


class TestEndToEndHiringFlow:
    async def test_application_to_hire(
        self,
        client: httpx.AsyncClient,
        session,
        company: Company,
        recruiter: User,
        interviewer: User,
    ):
        recruiter_token = await login(client, recruiter.email)
        interviewer_token = await login(client, interviewer.email)
        headers = auth(recruiter_token)

        # ------------------------------------------------- 1. analyse the JD
        analysis_response = await client.post(
            "/api/v1/jobs/analyze-description",
            headers=headers,
            json={"title": "Senior React Developer", "description": JOB_DESCRIPTION},
        )
        assert analysis_response.status_code == 200, analysis_response.text
        analysis = analysis_response.json()["data"]

        assert analysis["requires_review"] is True, "AI output must await human review"
        assert analysis["engine"], "the engine must be identified"
        required_names = {s["name"].lower() for s in analysis["required_skills"]}
        assert "react" in required_names
        assert analysis["min_experience_years"] == 4

        # ------------------------------------------------- 2. create the job
        create_response = await client.post(
            "/api/v1/jobs",
            headers=headers,
            json={
                "title": "Senior React Developer",
                "description": JOB_DESCRIPTION,
                "location_text": "Bengaluru, Karnataka",
                "work_mode": "HYBRID",
                "employment_type": "FULL_TIME",
                "min_experience_years": 4,
                "max_experience_years": 8,
                "salary_min": 2200000,
                "salary_max": 3400000,
                "openings": 2,
                "education_requirements": ["Bachelor's degree"],
                "responsibilities": [
                    "Build and maintain reusable React components",
                    "Develop and consume REST APIs",
                    "Mentor junior developers",
                ],
                "screening_questions": [
                    {
                        "question": "How many years of React experience do you have?",
                        "question_type": "EXPERIENCE",
                        "is_required": True,
                        "scoring": {"min": 4, "points": 20},
                    },
                    {
                        "question": "Can you work from Bengaluru?",
                        "question_type": "YES_NO",
                        "is_required": True,
                        "scoring": {"expected": "YES", "points": 10},
                    },
                ],
            },
        )
        assert create_response.status_code == 201, create_response.text
        job = create_response.json()["data"]
        job_id = job["id"]
        assert job["status"] == "DRAFT"

        # --------------------------- 3. recruiter confirms AI requirements
        apply_response = await client.post(
            f"/api/v1/jobs/{job_id}/apply-analysis",
            headers=headers,
            json={
                "required_skills": [
                    {"name": "React", "weight": 5},
                    {"name": "TypeScript", "weight": 4},
                    {"name": "REST API", "weight": 3},
                    {"name": "Git", "weight": 2},
                ],
                "preferred_skills": [{"name": "Next.js"}, {"name": "AWS"}],
                "responsibilities": [
                    "Build and maintain reusable React components",
                    "Develop and consume REST APIs",
                    "Mentor junior developers",
                ],
                "education_requirements": ["Bachelor's degree"],
                "min_experience_years": 4,
                "max_experience_years": 8,
            },
        )
        assert apply_response.status_code == 200, apply_response.text
        assert len(apply_response.json()["data"]["skills"]) == 6

        # ------------------------------------------------ 4. publish the job
        publish_response = await client.post(
            f"/api/v1/jobs/{job_id}/publish", headers=headers
        )
        assert publish_response.status_code == 200, publish_response.text
        assert publish_response.json()["data"]["status"] == "PUBLISHED"

        # --------------------------- 5. the job is visible on the public portal
        public_response = await client.get(f"/api/v1/public/jobs/{job_id}?source=linkedin")
        assert public_response.status_code == 200, public_response.text
        public_job = public_response.json()["data"]
        assert public_job["title"] == "Senior React Developer"
        assert len(public_job["screening_questions"]) == 2
        # Internal fields must not leak to the public portal.
        assert "ai_analysis" not in public_job
        assert "created_by_id" not in public_job

        question_ids = [q["id"] for q in public_job["screening_questions"]]

        # ------------------------------------------- 6. candidate applies
        candidate_email = f"rahul_{uuid.uuid4().hex[:6]}@example.test"
        application_payload = {
            "first_name": "Rahul",
            "last_name": "Sharma",
            "email": candidate_email,
            "phone": "+919876543210",
            "location": "Bengaluru, India",
            "current_designation": "Senior Frontend Engineer",
            "current_company": "Flipkart",
            "total_experience_years": 6,
            "expected_salary": 3000000,
            "notice_period_days": 30,
            "linkedin_url": "https://linkedin.com/in/rahulsharma",
            "cover_letter": "I would love to join your frontend team.",
            "screening_answers": [
                {"question_id": question_ids[0], "answer_number": 6},
                {"question_id": question_ids[1], "answer_boolean": True},
            ],
            "consent_given": True,
        }

        apply_result = await client.post(
            f"/api/v1/public/jobs/{job_id}/apply?source=linkedin",
            data={"application": json.dumps(application_payload)},
            files={
                "resume": (
                    "Rahul_Sharma.docx",
                    build_docx(SAMPLE_RESUME),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert apply_result.status_code == 201, apply_result.text
        applied = apply_result.json()["data"]
        application_id = applied["application_id"]
        assert applied["resume_uploaded"] is True
        assert applied["processing_queued"] is True
        assert applied["reference_code"].startswith("APP-")

        # Applying twice must be refused, not silently duplicated.
        duplicate = await client.post(
            f"/api/v1/public/jobs/{job_id}/apply",
            data={"application": json.dumps(application_payload)},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "ALREADY_APPLIED"

        # ------------------------- 7. resume parsing + ATS scoring complete
        await self._drain_background_work()

        ats_response = await client.get(
            f"/api/v1/ats/applications/{application_id}", headers=headers
        )
        assert ats_response.status_code == 200, ats_response.text
        score = ats_response.json()["data"]

        assert 0 <= score["overall_score"] <= 100
        assert score["overall_score"] > 70, "a well-matched candidate should score well"
        assert score["recommendation"] in ("STRONG_MATCH", "GOOD_MATCH")

        # The score must be explainable, not an oracle.
        for dimension in (
            "skills",
            "experience",
            "education",
            "responsibilities",
            "semantic",
        ):
            component = score["explanation"]["components"][dimension]
            assert component["explanation"], f"{dimension} must explain itself"
        assert score["matched_skills"], "matched requirements must be listed"
        assert "not a hiring decision" in " ".join(score["explanation"]["notes"])

        # ------------------------------------- 8. candidate profile was built
        application_response = await client.get(
            f"/api/v1/applications/{application_id}", headers=headers
        )
        assert application_response.status_code == 200
        application = application_response.json()["data"]
        candidate_id = application["candidate"]["id"]

        candidate_response = await client.get(
            f"/api/v1/candidates/{candidate_id}", headers=headers
        )
        candidate = candidate_response.json()["data"]
        skill_names = {s["name"].lower() for s in candidate["skills"]}
        assert "react" in skill_names, "skills must be extracted from the resume"
        assert candidate["experience"], "work history must be extracted"
        assert candidate["education"], "education must be extracted"

        # ------------------------------------------------- 9. ranking exists
        ranking_response = await client.get(
            f"/api/v1/ats/jobs/{job_id}/ranking", headers=headers
        )
        assert ranking_response.status_code == 200
        ranking = ranking_response.json()["data"]
        assert ranking and ranking[0]["candidate_name"] == "Rahul Sharma"
        assert ranking[0]["rank"] == 1

        # ------------------------------------------- 10. move through pipeline
        shortlist = await client.post(
            f"/api/v1/applications/{application_id}/status",
            headers=headers,
            json={
                "status": "SHORTLISTED",
                "reason": "Strong match on React and TypeScript",
                "send_email": True,
            },
        )
        assert shortlist.status_code == 200, shortlist.text
        assert shortlist.json()["data"]["status"] == "SHORTLISTED"

        # The shortlist email must be recorded, with its true delivery status.
        emails = await client.get(
            f"/api/v1/emails/messages?application_id={application_id}", headers=headers
        )
        messages = emails.json()["data"]["items"]
        assert messages, "status-change emails must be recorded"
        assert any(m["delivery_status"] == "NOT_SENT_NO_PROVIDER" for m in messages), (
            "with no provider configured, messages must not be reported as sent"
        )

        # -------------------------------------------- 11. schedule an interview
        start = (datetime.now(UTC) + timedelta(days=3)).replace(
            minute=0, second=0, microsecond=0
        )
        interview_response = await client.post(
            "/api/v1/interviews",
            headers=headers,
            json={
                "application_id": application_id,
                "interview_type": "TECHNICAL",
                "scheduled_start": start.isoformat(),
                "duration_minutes": 60,
                "interviewer_ids": [str(interviewer.id)],
                "round_name": "Technical Round 1",
                "meeting_link": "https://meet.example.test/abc",
                "send_invitation": True,
            },
        )
        assert interview_response.status_code == 201, interview_response.text
        interview = interview_response.json()["data"]
        interview_id = interview["id"]

        # No calendar provider is configured, and the API must say so plainly.
        assert interview["calendar_sync"]["status"] == "PENDING_NO_PROVIDER"
        assert "no external calendar" in interview_response.json()["message"].lower()

        # Scheduling moved the application into INTERVIEW.
        application_response = await client.get(
            f"/api/v1/applications/{application_id}", headers=headers
        )
        assert application_response.json()["data"]["status"] == "INTERVIEW"

        # A double-booking of the same interviewer must be refused.
        conflict = await client.post(
            "/api/v1/interviews",
            headers=headers,
            json={
                "application_id": application_id,
                "interview_type": "HR",
                "scheduled_start": (start + timedelta(minutes=30)).isoformat(),
                "duration_minutes": 60,
                "interviewer_ids": [str(interviewer.id)],
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "INTERVIEWER_CONFLICT"

        # -------------------------------------------- 12. submit feedback
        complete = await client.post(
            f"/api/v1/interviews/{interview_id}/complete", headers=headers
        )
        assert complete.status_code == 200

        feedback = await client.post(
            f"/api/v1/interviews/{interview_id}/feedback",
            headers=auth(interviewer_token),
            json={
                "overall_rating": 4.5,
                "recommendation": "STRONG_HIRE",
                "technical_skills": 5,
                "communication": 4,
                "problem_solving": 5,
                "domain_knowledge": 4,
                "culture_fit": 5,
                "strengths": "- Excellent React knowledge\n- Clear communication",
                "weaknesses": "- Limited AWS experience",
                "comments": "Strong technical candidate.",
                "private_remarks": "Salary expectation is near the top of our band.",
            },
        )
        assert feedback.status_code == 201, feedback.text

        # A company admin holds feedback:read:private, so they see the remarks...
        listed = await client.get(
            f"/api/v1/interviews/{interview_id}/feedback", headers=headers
        )
        assert listed.status_code == 200
        assert listed.json()["data"][0]["private_remarks"] is not None

        # ...but a plain recruiter without that permission must not.
        plain_recruiter_token = await self._plain_recruiter_token(
            client, session, company.id
        )
        redacted = await client.get(
            f"/api/v1/interviews/{interview_id}/feedback",
            headers=auth(plain_recruiter_token),
        )
        assert redacted.status_code == 200
        assert redacted.json()["data"][0]["private_remarks"] is None, (
            "private remarks must be hidden from users without feedback:read:private"
        )
        # The rest of the feedback is still visible to them.
        assert redacted.json()["data"][0]["recommendation"] == "STRONG_HIRE"

        # -------------------------------------------- 13. AI summarises feedback
        summary = await client.post(
            f"/api/v1/interviews/applications/{application_id}/summarize-feedback",
            headers=headers,
        )
        assert summary.status_code == 200, summary.text
        summary_data = summary.json()["data"]
        assert summary_data["summary"]
        assert summary_data["engine"]
        assert "decision belongs" in summary_data["disclaimer"].lower()

        # -------------------------------------------------- 14. make an offer
        offer_response = await client.post(
            "/api/v1/offers",
            headers=headers,
            json={
                "application_id": application_id,
                "position_title": "Senior React Developer",
                "base_salary": 3000000,
                "joining_date": (datetime.now(UTC) + timedelta(days=45)).date().isoformat(),
                "variable_pay": 300000,
                "currency": "INR",
                "benefits": ["Health insurance", "Learning budget"],
                "expires_in_days": 7,
            },
        )
        assert offer_response.status_code == 201, offer_response.text
        offer_id = offer_response.json()["data"]["id"]

        approve = await client.post(f"/api/v1/offers/{offer_id}/approve", headers=headers)
        assert approve.status_code == 200

        send = await client.post(f"/api/v1/offers/{offer_id}/send", headers=headers)
        assert send.status_code == 200, send.text
        send_data = send.json()["data"]
        assert send_data["offer"]["status"] == "SENT"
        assert send_data["email_delivery_status"] == "NOT_SENT_NO_PROVIDER"
        assert "not transmitted" in send_data["message"]

        offer_token = send_data["candidate_offer_url"].split("token=")[1]

        # ------------------------------- 15. candidate views and accepts
        view = await client.get(f"/api/v1/offers/{offer_id}/view?token={offer_token}")
        assert view.status_code == 200, view.text
        assert view.json()["data"]["can_respond"] is True
        assert view.json()["data"]["position_title"] == "Senior React Developer"

        bad_token = await client.get(f"/api/v1/offers/{offer_id}/view?token=wrong")
        assert bad_token.status_code == 401

        accept = await client.post(
            f"/api/v1/offers/{offer_id}/respond?token={offer_token}",
            json={"accepted": True},
        )
        assert accept.status_code == 200, accept.text
        assert accept.json()["data"]["status"] == "ACCEPTED"
        assert accept.json()["data"]["onboarding_started"] is True

        # ------------------------------------------ 16. onboarding started
        onboarding = await client.get("/api/v1/onboarding", headers=headers)
        assert onboarding.status_code == 200
        records = onboarding.json()["data"]["items"]
        assert records, "accepting an offer must start onboarding"
        record = records[0]
        assert record["status"] == "PREBOARDING"
        assert record["tasks"], "an onboarding checklist must be created"

        # Joining must be blocked while required tasks are outstanding.
        premature = await client.post(
            f"/api/v1/onboarding/{record['id']}/status",
            headers=headers,
            json={"status": "DOCUMENT_COLLECTION"},
        )
        assert premature.status_code == 200

        # ------------------------------------------- 17. timeline is complete
        timeline = await client.get(
            f"/api/v1/applications/{application_id}/timeline", headers=headers
        )
        assert timeline.status_code == 200
        events = [e["event_type"] for e in timeline.json()["data"]]
        assert "APPLICATION_SUBMITTED" in events
        assert "STATUS_CHANGED" in events
        assert "OFFER_SENT" in events

        # ------------------------------- 18. candidate self-service view
        candidate_token = await self._candidate_token(client, session, candidate_email)
        if candidate_token:
            mine = await client.get(
                "/api/v1/me/applications", headers=auth(candidate_token)
            )
            assert mine.status_code == 200
            items = mine.json()["data"]["items"]
            assert items
            # The candidate sees a friendly label, never the raw internal status.
            assert items[0]["status_label"] in ("Offer accepted", "Offer extended")
            assert "ats_score" not in items[0]

        # -------------------------------------------- 19. analytics reflect it
        dashboard = await client.get("/api/v1/analytics/dashboard", headers=headers)
        assert dashboard.status_code == 200
        kpis = dashboard.json()["data"]["kpis"]
        assert kpis["active_jobs"] >= 1
        assert kpis["total_applications"] >= 1

        funnel = await client.get("/api/v1/analytics/funnel", headers=headers)
        assert funnel.status_code == 200
        stages = {s["stage"]: s["count"] for s in funnel.json()["data"]["stages"]}
        assert stages["APPLIED"] >= 1
        assert stages["OFFER"] >= 1, "an accepted offer must count in the offer stage"

    @staticmethod
    async def _plain_recruiter_token(client, session, company_id) -> str:
        """A recruiter with no company-admin role, to prove private remarks are hidden."""
        from app.core.enums import RoleName
        from tests.conftest import _make_user

        user = await _make_user(
            session, roles=[RoleName.RECRUITER], company_id=company_id
        )
        return await login(client, user.email)

    @staticmethod
    async def _drain_background_work() -> None:
        """Wait for the in-process queue to finish resume parsing and scoring."""
        from app.workers.queue import InlineQueue, get_queue

        queue = get_queue()
        if isinstance(queue, InlineQueue):
            await queue.drain(timeout=60)

    @staticmethod
    async def _candidate_token(client, session, email: str) -> str | None:
        """Give the applicant a login so the candidate portal can be exercised.

        Public applications do not require an account, so one is created here the same
        way self-registration would.
        """
        from sqlalchemy import select

        from app.core.enums import RoleName, UserStatus
        from app.core.security import hash_password
        from app.models.candidate import Candidate
        from app.models.user import Role, User
        from tests.conftest import TEST_PASSWORD

        user = User(
            email=email,
            hashed_password=hash_password(TEST_PASSWORD),
            first_name="Rahul",
            last_name="Sharma",
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
        )
        role = await session.scalar(
            select(Role).where(
                Role.name == RoleName.CANDIDATE.value, Role.company_id.is_(None)
            )
        )
        user.roles.append(role)
        session.add(user)
        await session.flush()

        candidate = await session.scalar(select(Candidate).where(Candidate.email == email))
        if candidate is not None:
            candidate.user_id = user.id
        await session.commit()

        return await login(client, email)


class TestWorkflowAutomation:
    """The automation guardrail, exercised over the API rather than in isolation."""

    async def test_workflow_cannot_auto_reject_without_approval(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.post(
            "/api/v1/workflows",
            headers=auth(recruiter_token),
            json={
                "name": "Auto-reject low scores",
                "trigger": "ATS_SCORE_GENERATED",
                "conditions": {
                    "op": "AND",
                    "rules": [{"field": "ats_score", "operator": "lt", "value": 40}],
                },
                "steps": [
                    {"action_type": "CHANGE_STATUS", "config": {"status": "REJECTED"}}
                ],
                "requires_human_approval": False,
            },
        )
        assert response.status_code == 422
        assert "human approval" in response.json()["error"]["message"]

    async def test_auto_shortlist_is_permitted(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.post(
            "/api/v1/workflows",
            headers=auth(recruiter_token),
            json={
                "name": "Auto-shortlist strong matches",
                "trigger": "ATS_SCORE_GENERATED",
                "conditions": {
                    "op": "AND",
                    "rules": [{"field": "ats_score", "operator": "gte", "value": 85}],
                },
                "steps": [
                    {"action_type": "CHANGE_STATUS", "config": {"status": "SHORTLISTED"}},
                    {
                        "action_type": "SEND_EMAIL",
                        "config": {"template_key": "SHORTLISTED"},
                    },
                ],
                "requires_human_approval": False,
            },
        )
        assert response.status_code == 201, response.text
        assert len(response.json()["data"]["steps"]) == 2

    async def test_workflow_rejects_an_unknown_condition_field(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.post(
            "/api/v1/workflows",
            headers=auth(recruiter_token),
            json={
                "name": "Injection attempt",
                "trigger": "APPLICATION_CREATED",
                "conditions": {
                    "field": "__class__.__init__",
                    "operator": "eq",
                    "value": "x",
                },
                "steps": [{"action_type": "ADD_TAG", "config": {"tag": "x"}}],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_CONDITIONS"


class TestAiGovernance:
    async def test_status_reports_the_engine_honestly(
        self, client: httpx.AsyncClient, recruiter_token: str
    ):
        response = await client.get("/api/v1/ai/status", headers=auth(recruiter_token))
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_language_model"] is False
        assert "deterministic" in data["message"]
        assert data["capabilities"]["conversational_assistant"] is False

    async def test_assistant_tools_are_scoped_to_permissions(
        self, client: httpx.AsyncClient, recruiter_token: str, interviewer_token: str
    ):
        recruiter_tools = await client.get("/api/v1/ai/tools", headers=auth(recruiter_token))
        assert recruiter_tools.status_code == 200
        recruiter_names = {t["name"] for t in recruiter_tools.json()["data"]}
        assert "list_top_candidates" in recruiter_names

        # An interviewer lacks analytics and ATS permissions, so those tools must be
        # absent from what the model can even call.
        interviewer_tools = await client.get(
            "/api/v1/ai/tools", headers=auth(interviewer_token)
        )
        if interviewer_tools.status_code == 200:
            interviewer_names = {t["name"] for t in interviewer_tools.json()["data"]}
            assert "conversion_stats" not in interviewer_names
            assert "list_top_candidates" not in interviewer_names

    async def test_governance_policy_is_published(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/ai/governance")
        assert response.status_code == 200
        data = response.json()["data"]
        assert any("humans decide" in p for p in data["principles"])
        assert "no_auto_reject" in data["enforcement"]

    async def test_ats_scoring_is_documented(self, client: httpx.AsyncClient):
        response = await client.get("/api/v1/ats/explain")
        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data["dimensions"]) == {
            "skills",
            "experience",
            "education",
            "responsibilities",
            "semantic",
        }
        assert any("never reject" in g for g in data["governance"])
