# HireHQ

**From Application to Hire — Automated.**

An AI-assisted applicant tracking system, job portal and recruitment automation platform.
HireHQ parses every resume, scores every application against the role with a breakdown a
recruiter can actually read, and moves candidates through a configurable pipeline — while
keeping every consequential decision with an authorised human.

---

## Contents

- [Quick start](#quick-start)
- [Demo accounts](#demo-accounts)
- [What is built](#what-is-built)
- [Architecture](#architecture)
- [The ATS engine](#the-ats-engine)
- [Automation and AI governance](#automation-and-ai-governance)
- [Configuration](#configuration)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Deployment — plain English](DEPLOY-SIMPLE.md)
- [Deployment — technical](DEPLOYMENT.md)
- [Known limitations](#known-limitations)

---

## Quick start

### Option A — Docker (everything, one command)

```bash
cp .env.example .env
docker compose up --build
```

Brings up PostgreSQL, Redis, MinIO, the API, the background worker and the frontend.
Migrations run and demo data seeds automatically before the API starts.

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| API docs (ReDoc) | http://localhost:8000/redoc |
| MinIO console | http://localhost:9001 (`hirehq` / `hirehq-secret`) |

### Option B — Local, no infrastructure

The backend runs on SQLite with local file storage and the built-in AI engine, so nothing
external is required.

```bash
# ---- backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -e .

cp ../.env.example .env
python -m app.db.seed           # creates the schema and demo data
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

```bash
# ---- frontend (second terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                     # http://localhost:3000
```

Re-seed at any time with `python -m app.db.seed --reset`.

---

## Demo accounts

Seeded by `python -m app.db.seed`. Passwords come from `.env`
(`SEED_SUPER_ADMIN_PASSWORD`, `SEED_DEMO_PASSWORD`) — change them before exposing any
environment.

| Role | Email | Password |
| --- | --- | --- |
| Super Admin | `admin@hirehq.test` | `ChangeMe!2024` |
| Company Admin | `priya.nair@northwind.test` | `Demo!2024Pass` |
| Recruiter | `arjun.mehta@northwind.test` | `Demo!2024Pass` |
| Hiring Manager | `vikram.desai@northwind.test` | `Demo!2024Pass` |
| Interviewer | `rohan.gupta@northwind.test` | `Demo!2024Pass` |
| Candidate | `rahul.sharma@example.test` | `Demo!2024Pass` |

The seed creates one company with 10 staff, 10 jobs, 20 candidates and 25 applications.
Every application is scored by the real ATS engine, and every resume is a genuine `.docx`
put through the real parser — so the demo data is also an end-to-end smoke test.

---

## What is built

### Working end to end

- **Authentication & RBAC** — register, login, refresh with rotation and replay
  detection, email verification, password reset, 7 roles, ~60 granular permissions.
- **Multi-tenancy** — every company-scoped query is filtered by `company_id` at the
  repository layer; cross-tenant reads return 404, never 403.
- **Jobs** — full lifecycle (draft → published → paused → closed → archived), duplication,
  hiring teams, screening questions, publication readiness checks.
- **AI job-description analysis** — extracts required/preferred skills, experience,
  education and responsibilities for the recruiter to **review and confirm** before
  anything reaches the job.
- **Public job portal** — search, filter, job detail, multi-step apply with resume upload,
  source attribution (`?source=linkedin`), and reference-code tracking without an account.
- **Resume pipeline** — validation → structural scan → storage → text extraction (PDF and
  DOCX) → parsing → profile merge → ATS scoring, all off the request thread.
- **Explainable ATS engine** — five weighted dimensions, per-skill importance, alias-aware
  matching, full reasoning stored with every score. See [below](#the-ats-engine).
- **Pipeline** — 15 statuses with an enforced state machine, Kanban board with
  drag-and-drop, bulk actions (status, assign, tag, email, talent pool).
- **Screening** — configurable question scoring; knockout answers raise a review flag and
  never auto-reject.
- **Interviews** — conflict-checked scheduling, multiple rounds, calendar event creation,
  reminders, structured feedback with private remarks, AI feedback summarisation.
- **Offers & onboarding** — draft → approve → send (tokenised candidate link) → accept →
  onboarding checklist, with joining blocked until required tasks complete.
- **Workflow automation** — trigger/condition/action engine with an allow-listed field
  grammar, idempotent execution, per-run audit trail and a human-approval gate.
- **Talent pool & referrals** — reusable pools, saved-search refresh, AI matching of
  existing candidates to a new job, employee referrals with analytics.
- **Analytics** — funnel with stage conversion, source performance, ATS distribution,
  time-to-hire and time-in-stage, job and recruiter performance, drop-off.
- **AI recruiter assistant** — answers questions using permission-scoped tools; the model
  never touches the database.
- **Audit** — append-only audit log plus a separate AI decision log recording engine,
  output and human review outcome.
- **Integrations** — signed, purpose-scoped OAuth for Google and Microsoft, with tokens
  encrypted at rest (AES-256-GCM) and refreshed transparently. Calendar sync creates real
  invitations; mailbox sync imports candidate replies read-only and matches them to the
  right application.
- **Live updates** — server-sent events push new applications, finished ATS runs, pipeline
  moves, interviews, feedback and offers to open dashboards. Events are hints to refetch,
  never data: the numbers always come back through the permission-checked endpoints.

### Frontend

42 routes. The public portal and multi-step application flow; the full auth set (sign in,
register, forgot/reset password, email verification, application tracking without an
account); tokenised candidate pages for offers and assessments; the recruiter workspace
(dashboard, jobs and job detail, ranked applicants, Kanban pipeline, candidates, ATS
breakdown, interviews and feedback, calendar, offers, assessments and grading, talent
pool, inbox, workflow builder, analytics, assistant); the admin console (platform
overview, companies, users, audit log); role-specific homes for hiring managers and
interviewers; the candidate portal (dashboard, applications, interviews, offers); and
shared profile settings.

---

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────┐     ┌────────────┐
│  Next.js    │────▶│              FastAPI                 │────▶│ PostgreSQL │
│  frontend   │◀────│  routers → services → repositories   │◀────│            │
└─────────────┘     └───────────────┬──────────────────────┘     └────────────┘
                                    │ domain events
                                    ▼
                    ┌───────────────────────────────┐      ┌────────────┐
                    │  workflow engine │ notifier    │─────▶│   Redis    │
                    └───────────────────────────────┘      │  + worker  │
                                    │                      └────────────┘
                    ┌───────────────┴───────────────┐
                    │        provider layer         │
                    │  AI · storage · email · cal   │
                    └───────────────────────────────┘
```

**Layering.** Routers do HTTP and authorisation. Services hold business logic and are the
only place that mutates domain state. Repositories own query construction —
`TenantRepository` cannot be constructed without a company, which is what makes tenant
isolation structural rather than a discipline.

**Domain events.** Services publish facts (`APPLICATION_CREATED`, `ATS_SCORE_GENERATED`);
the workflow engine and notification service subscribe. Events are dispatched **after
commit**, so a subscriber never acts on a transaction that later rolls back.

**Provider abstraction.** AI, storage, email and calendar are all behind interfaces with a
real implementation and an honest fallback. Nothing pretends: an unconfigured email
transport records `NOT_SENT_NO_PROVIDER`, an unconfigured calendar reports
`PENDING_NO_PROVIDER`, and an unscanned file is `NOT_SCANNED` — never `CLEAN`.

**Database portability.** PostgreSQL is the target; portable type decorators (`GUID`,
`JSONType`, `UTCDateTime`) let the identical schema and every test run on SQLite with no
infrastructure.

---

## The ATS engine

Deliberately **not** keyword counting. `app/modules/ats/engine.py` is pure — no I/O, no
clock — so it is exhaustively unit-tested and any score can be recomputed and verified.

| Dimension | Default weight | What it measures |
| --- | --- | --- |
| Skills | 40% | Weighted coverage of required and preferred skills. Alias-aware: `ReactJS` satisfies `React`. Each skill carries its own 1–5 importance. |
| Experience | 25% | Years against the job's band. Meeting the minimum scores 100; falling short degrades proportionally rather than to zero. Exceeding the band is capped, never below 80. |
| Education | 10% | Highest attained level against the highest required. One rung short scores 60, two rungs 30. |
| Responsibilities | 15% | How much of the job's actual work the candidate has evidence of doing. This is what separates "has the keyword" from "has done the work". |
| Semantic | 10% | Similarity in meaning between resume and description, so different vocabulary for the same work still matches. |

Weights are configurable per company and per job, are normalised at scoring time (any
positive numbers work), and are **stored with each score** so an old result stays
explainable after the profile is edited.

```
GET /api/v1/ats/applications/{id}
{
  "overall_score": 93.27,
  "recommendation": "STRONG_MATCH",
  "explanation": {
    "summary": "Overall 93.27% - strong match. Strongest area: experience (100%)...",
    "components": {
      "skills": {
        "score": 97.2, "weight": 0.40, "contribution": 38.88,
        "explanation": "Matched 6 of 6 required skills, 3 of 4 preferred skills."
      },
      ...
    },
    "matched_skills": ["React", "TypeScript", "REST API", "Git"],
    "missing_skills": ["GraphQL"],
    "notes": ["This score ranks applications against the requirements written on the job. It is a screening aid, not a hiring decision."]
  }
}
```

`GET /api/v1/ats/explain` documents the model for recruiters and compliance review.

---

## Automation and AI governance

The product principle: **automate repetitive recruitment operations while keeping final
hiring decisions under authorised human control.** That is enforced in code, not policy:

- **No automatic rejection.** The workflow engine refuses to move an application to
  `REJECTED`, `HIRED` or `OFFER` unless the workflow has `requires_human_approval` — checked
  both when a workflow is saved *and* again at execution. Adverse screening outcomes route
  to manual review.
- **AI proposes, humans dispose.** Job-description analysis returns
  `requires_review: true` and is never applied until a recruiter POSTs the confirmed
  requirements back.
- **Protected attributes.** Never inferred, never stored — the parser schema has no field
  for them and the ATS engine has no dimension that could use them. The AI system prompt
  forbids it, and that prompt is not the only line of defence.
- **RBAC for the assistant.** The model has no database access. It can only call tools
  pre-bound to the caller's company and filtered by their permissions, so an interviewer's
  assistant cannot see analytics.
- **Auditability.** `ai_decision_logs` records feature, engine, model, a non-sensitive
  input digest, the output summary and whether a human accepted, edited or overrode it.
- **Honest engine labelling.** Every AI response carries the engine that produced it
  (`heuristic-v1` or `anthropic:claude-opus-5`); the UI badges it so the deterministic
  fallback is never mistaken for a language model.

`GET /api/v1/ai/governance` publishes these commitments and how each is enforced.

---

## Configuration

Everything is environment-driven — see [`.env.example`](.env.example) for the annotated
list. The defaults run the entire product with zero external services.

| Concern | Default (dev) | Production |
| --- | --- | --- |
| Database | SQLite | PostgreSQL (`postgresql+asyncpg://…`) |
| Queue | in-process | Redis + ARQ worker (`USE_REDIS_QUEUE=true`) |
| Storage | local filesystem | S3-compatible (`STORAGE_PROVIDER=s3`) |
| AI | `heuristic` — real algorithms, no network | `anthropic` + `AI_API_KEY` |
| Email | `console` — records, does not send | `smtp` + `SMTP_HOST` |
| Calendar | none | `google` / `microsoft` via OAuth |
| Mailbox sync | not connected | `google` / `microsoft`, read-only scopes |
| Code execution | `sqlite` — SQL only | `remote` + a sandbox you operate |
| Malware scan | structural checks only | `clamav` |

Setting `APP_ENV=production` makes startup **refuse** a default `JWT_SECRET`, `DEBUG=true`,
or local file storage.

### Enabling the real AI provider

```env
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-...
AI_MODEL=claude-opus-5
```

This upgrades resume parsing, job-description analysis, semantic matching, summaries and
turns the assistant into a genuine conversational agent with tool calling. Without it the
deterministic engine handles all of those except free-form conversation — and says so.

---

## Testing

```bash
cd backend
pytest                      # 295 tests
pytest --cov=app            # with coverage
ruff check app tests        # lint
```

| Suite | Covers |
| --- | --- |
| `test_ats_engine.py` | 46 tests: weights, every dimension, bounds, determinism, explainability, ranking |
| `test_resume_parser.py` | Extraction, upload validation, structural scanning, field extraction, skill normalisation, parsing, JD analysis, semantic similarity |
| `test_state_machine.py` | Every transition, terminal states, funnel maths, candidate-facing labels |
| `test_workflows.py` | Condition grammar, injection rejection, operators, **automation guardrails** |
| `test_education_matching.py` | Regression tests for two substring bugs found during development |
| `test_api_auth.py` | Registration, login, token rotation and replay, RBAC, **tenant isolation over HTTP** |
| `test_e2e_hiring_flow.py` | The complete acceptance test below |

The end-to-end test drives the real HTTP API through the entire product:

> analyse JD → create job → confirm requirements → publish → find on public portal →
> apply with a real `.docx` → resume parsed → ATS scored → ranked → workflow shortlists →
> email recorded → interview scheduled → feedback submitted → AI summarises →
> offer sent → candidate accepts → onboarding starts → timeline and analytics reflect it

It also asserts the guarantees, not just the happy path: duplicate applications are
refused, invalid transitions are rejected with the allowed set, private interviewer
remarks are hidden from users without `feedback:read:private`, double-booking an
interviewer is refused, and no internal field leaks to the public portal.

---

## Project layout

```
HireHQ/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── alembic/                  # migrations (initial schema: 56 tables, 321 indexes)
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                 # config, security, enums, permissions, exceptions
│   │   ├── db/                   # base, session, portable types, bootstrap, seed
│   │   ├── models/               # 56 SQLAlchemy models
│   │   ├── repositories/         # BaseRepository, TenantRepository
│   │   ├── providers/            # ai/ storage email calendar scanning
│   │   ├── middleware/           # request context, security headers, rate limit, errors
│   │   ├── dependencies/         # auth, RBAC, tenant scope
│   │   ├── services/             # audit, events, subscribers
│   │   ├── modules/              # 23 feature modules (router + service + schemas)
│   │   ├── workers/              # queue abstraction, tasks, ARQ worker
│   │   └── utils/                # text, skills
│   └── tests/                    # 237 tests
└── frontend/
    └── src/
        ├── app/                  # App Router pages
        ├── components/           # ui.tsx, app-shell, apply-dialog, marketing
        └── lib/                  # api client, auth, types, utils
```

---

## Known limitations

Stated plainly rather than discovered later:

- **Code execution for assessments.** SQL answers are graded against a disposable
  in-memory SQLite database, which is genuinely safe to run in-process. Other languages
  need a sandbox you operate (`CODE_RUNNER=remote`); without one, coding submissions are
  stored and reported as awaiting a human grader. A runner that cannot execute a
  submission always reports *not graded*, never *failed*.
- **OCR.** Scanned image-only PDFs cannot be parsed. The pipeline detects this and flags
  the resume rather than storing an empty profile.
- **Rate limiting** is per-process, appropriate as a safety net behind a proper ingress
  limiter, not as a distributed quota system.
- **Live updates are per-process.** Behind multiple workers each process serves its own
  SSE subscribers. That is fine here because events are hints to refetch rather than
  authoritative state — a client connected to a quiet worker sees a slightly later
  refresh, never wrong data. A shared broker would be needed to make delivery uniform.
- **Mailbox sync needs the worker.** The `sync_mailboxes` cron job runs every five minutes
  under ARQ. Without a worker, use `POST /emails/accounts/{id}/sync` to pull on demand.
- **Token encryption is derived from `JWT_SECRET`.** Rotating that secret invalidates
  stored OAuth tokens along with sessions, so calendars and mailboxes must be reconnected.
  A dedicated key would decouple the two.

---

## API documentation

With the server running: **http://localhost:8000/docs** (Swagger) or **/redoc**.

210 operations across 25 tags. Every endpoint has request and response schemas,
authentication, authorisation, validation and error handling. Sign in via
`POST /api/v1/auth/login`, click **Authorize**, paste the `access_token`, and the whole API
is callable with that identity's permissions.

Response envelope:

```jsonc
// success
{ "success": true, "data": { }, "message": "Application created successfully" }

// error
{ "success": false, "error": { "code": "APPLICATION_NOT_FOUND", "message": "Application not found" } }
```
