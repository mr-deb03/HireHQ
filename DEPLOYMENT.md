# Deploying HireHQ

Vercel hosts the **frontend**. Render hosts the **backend** — it cannot run on Vercel, see
[why](#appendix--why-the-backend-does-not-go-on-vercel) — and the browser talks to it
directly.

```
        ┌──────────────┐   HTTPS + SSE    ┌──────────────────┐
Browser │   Vercel     │ ───────────────▶ │  Render web      │──▶ Postgres   (Neon)
   │    │  (Next.js)   │ ◀─────────────── │  service         │──▶ Redis      (Upstash)
   └───▶└──────────────┘                  └──────────────────┘──▶ S3 storage (R2 / AWS)
                                          ┌──────────────────┐
                                          │  Render worker   │  same image, same env,
                                          └──────────────────┘  different start command
```

Every page is a client component, so Vercel serves static HTML + JS and **all API calls go
browser → Render**. Vercel never proxies them. That is what lets server-sent events work.

The repository contains [`render.yaml`](render.yaml), a Render **Blueprint** that creates
both backend services already wired to the same secrets. Most of step 6 is one click.

Total time: about 40 minutes.

---

## Contents

1. [What it costs](#step-0--what-it-costs)
2. [Push to GitHub](#step-1--push-the-code-to-github)
3. [Postgres (Neon)](#step-2--postgres-on-neon)
4. [Redis (Upstash)](#step-3--redis-on-upstash)
5. [Storage (Cloudflare R2)](#step-4--object-storage-on-cloudflare-r2)
6. [Run the migrations](#step-5--run-the-migrations)
7. [Backend (Render Blueprint)](#step-6--deploy-the-backend-on-render)
8. [Frontend (Vercel)](#step-7--deploy-the-frontend-on-vercel)
9. [Close the CORS loop](#step-8--close-the-cors-loop)
10. [Verify](#step-9--verify-the-live-deployment)
11. [First real login](#step-10--create-your-first-account)
12. [Optional: email, calendar, AI](#optional-extras)
13. [Troubleshooting](#troubleshooting)

---

## Step 0 — What it costs

Stated up front because Render's free tier has two limits that matter here.

| Service | Free tier | What the guide assumes |
| --- | --- | --- |
| Neon Postgres | Yes (scales to zero) | Free |
| Upstash Redis | Yes (10k commands/day) | Free |
| Cloudflare R2 | Yes (10 GB, no egress fees) | Free |
| Vercel | Yes (hobby) | Free |
| **Render web service** | Yes — **but sleeps after 15 min idle**, ~50 s cold start | **Starter, $7/mo** |
| **Render background worker** | **No free tier** | **Starter, $7/mo** |

So the setup below is **$14/month**. There is a genuine free path — see
[Running without a worker](#running-without-a-worker-free-tier) — but read what it costs
you in capability before choosing it.

Accounts needed: [GitHub](https://github.com), [Neon](https://neon.tech),
[Upstash](https://upstash.com), [Cloudflare](https://dash.cloudflare.com),
[Render](https://render.com), [Vercel](https://vercel.com).

---

## Step 1 — Push the code to GitHub

There is no git repository yet. From the project root:

```bash
cd HireHQ
git init
git add .
git commit -m "HireHQ"
git branch -M main
```

**Before pushing, confirm no secrets are staged.** `.gitignore` covers `.env`,
`.env.local`, `*.db` and `storage/`, but check rather than trust:

```bash
git ls-files | grep -E "\.env$|\.env\.local$|\.db$|/storage/"
```

That must print **nothing**. If it prints a file: `git rm --cached <file>`, add it to
`.gitignore`, commit again.

Create an empty repo on GitHub (no README, no .gitignore — you have both), then:

```bash
git remote add origin https://github.com/<your-username>/hirehq.git
git push -u origin main
```

---

## Step 2 — Postgres on Neon

1. [console.neon.tech](https://console.neon.tech) → **New Project**, name it `hirehq`.
   Pick a region near Render's (the blueprint uses `oregon` — change both if you prefer
   Frankfurt or Singapore).
2. Copy the **connection string** from the dashboard:

   ```
   postgresql://neondb_owner:npg_XXXX@ep-cool-mud-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

3. **Rewrite it for asyncpg.** Both edits are required:

   - `postgresql://` → `postgresql+asyncpg://`
   - delete `?sslmode=require` — asyncpg rejects that parameter with
     `TypeError: connect() got an unexpected keyword argument 'sslmode'`. Neon enforces
     TLS regardless and asyncpg negotiates it, so nothing is lost.

   Save this form — you need it in steps 5 and 6:

   ```
   postgresql+asyncpg://neondb_owner:npg_XXXX@ep-cool-mud-12345.us-east-2.aws.neon.tech/neondb
   ```

> Neon's free tier scales to zero. The first query after an idle period wakes it and takes
> a few seconds. That is a cold start, not a fault.

---

## Step 3 — Redis on Upstash

1. [console.upstash.com](https://console.upstash.com) → **Create Database** → Redis.
2. Name `hirehq`, region near Render, **Eviction: disabled**.

   Eviction must stay off. This Redis is a job queue, not a cache — an evicted key is a
   résumé that never gets parsed.

3. Copy the **TCP connection string** (not the REST URL):

   ```
   rediss://default:AXXXXXaaa@fine-cat-12345.upstash.io:6379
   ```

   It must begin `rediss://` — two s's, meaning TLS. ARQ reads TLS from that scheme
   automatically; verified against this codebase.

---

## Step 4 — Object storage on Cloudflare R2

R2 charges no egress, which matters because every résumé download is egress.

1. [Cloudflare dashboard](https://dash.cloudflare.com) → **R2** → **Create bucket**,
   named `hirehq`.
2. **Do not enable public access.** Every file is served through a short-lived signed URL;
   nothing should be reachable without one.
3. **R2 → Manage R2 API Tokens → Create API Token**
   - Permissions **Object Read & Write**, scoped to the `hirehq` bucket
   - Copy the **Access Key ID**, **Secret Access Key** (shown once) and the **S3
     endpoint**: `https://<account-id>.r2.cloudflarestorage.com`

4. **R2 needs one setting empty.** R2 encrypts every object automatically and *rejects*
   the `x-amz-server-side-encryption` header AWS S3 expects. The blueprint already sets
   `STORAGE_SERVER_SIDE_ENCRYPTION=""` for this reason.

   **Using AWS S3 or MinIO instead?** Set it to `AES256` in `render.yaml` and put your real
   region in `STORAGE_REGION` (R2 uses `auto`).

---

## Step 5 — Run the migrations

Do this **before** the first deploy. The app does not create tables on Postgres — Alembic
owns the schema there, so the API starts and then fails every query until this is done.

Render's Shell and Pre-Deploy Command are paid features, so the reliable route on any plan
is from your own machine against the Neon database, which is publicly reachable:

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://neondb_owner:npg_XXXX@ep-....neon.tech/neondb" \
  .venv/Scripts/python -m alembic upgrade head
```

PowerShell has no inline environment-variable prefix, so set it separately there:

```powershell
cd backend
$env:DATABASE_URL="postgresql+asyncpg://neondb_owner:npg_XXXX@ep-....neon.tech/neondb"
.venv\Scripts\python -m alembic upgrade head
```

On macOS or Linux use `.venv/bin/python`. Expected final line:

```
INFO  [alembic.runtime.migration] Running upgrade  -> d8a311cc31fa, initial schema
```

Verify the schema landed:

```bash
DATABASE_URL="postgresql+asyncpg://..." .venv/Scripts/python -c "
import asyncio
from sqlalchemy import text
from app.db.session import session_scope
async def main():
    async with session_scope() as s:
        n = (await s.execute(text(
            \"select count(*) from information_schema.tables where table_schema='public'\"
        ))).scalar_one()
        print(f'{n} tables')
asyncio.run(main())"
```

You should see **57 tables**.

> Re-run this same command after any future `git pull` that adds a migration. Render will
> not do it for you unless you configure a Pre-Deploy Command on a paid instance.

---

## Step 6 — Deploy the backend on Render

The repository root contains [`render.yaml`](render.yaml), which defines the API and the
worker together and shares one env-var group between them — so `JWT_SECRET` cannot drift
between the two services. That matters more than it looks: it signs sessions *and* derives
the encryption key for stored OAuth tokens, so mismatched values would leave the worker
unable to decrypt what the API wrote.

1. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Blueprint**.
2. Connect your GitHub account and pick the `hirehq` repository.
3. Render reads `render.yaml` and shows two services to be created: **hirehq-api** (web)
   and **hirehq-worker** (worker). Give the blueprint a name.
4. Render prompts for every value marked `sync: false`. Fill in:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | the rewritten Neon URL from step 2 |
   | `REDIS_URL` | the `rediss://` URL from step 3 |
   | `STORAGE_ENDPOINT` | `https://<account-id>.r2.cloudflarestorage.com` |
   | `STORAGE_ACCESS_KEY` | R2 access key id |
   | `STORAGE_SECRET_KEY` | R2 secret access key |
   | `BACKEND_BASE_URL` | `https://hirehq-api.onrender.com` |
   | `FRONTEND_BASE_URL` | `https://placeholder.vercel.app` — corrected in step 8 |
   | `CORS_ORIGINS` | `https://placeholder.vercel.app` — corrected in step 8 |

   `BACKEND_BASE_URL` is this API's own public URL. Render derives it from the service
   name in `render.yaml`, so it is `https://hirehq-api.onrender.com` unless that name was
   already taken — check the service page after step 5 and correct it if Render assigned
   a suffix. It builds the OAuth redirect URIs, so it has to be exact.

   The last two are placeholders because the Vercel URL does not exist yet. The services
   deploy and pass their health checks regardless; only the browser is blocked until
   step 8 fixes them.

   `JWT_SECRET` is generated by Render and shared automatically. You never see or set it.

5. **Apply.** First build takes 5–10 minutes (it compiles the Python dependencies).

6. Copy the API's URL from its service page — `https://hirehq-api.onrender.com` or
   similar.

A healthy API boot ends with:

```
starting   app=HireHQ env=production database=postgresql+asyncpg
schema_managed_by_alembic  url_scheme=postgresql+asyncpg
ai_running_without_model   detail=Using the deterministic heuristic engine...
email_not_transmitting     detail=Emails will be recorded but not delivered...
started    providers={'ai': ..., 'storage': ..., 'email': ..., 'calendar': ...}
```

Those two warnings are expected on a first deployment — the app stating plainly what is
not configured yet, not a failure. See [Optional extras](#optional-extras). The line that
means *up* is `started`.

A healthy **worker** boot ends with:

```
worker_starting  tasks=['expire_offers', 'parse_resume', 'score_application', 'sync_mailboxes', ...]
```

**If a service exits instead**, the message names the cause. `APP_ENV=production` refuses
a default `JWT_SECRET`, refuses `DEBUG=true`, and refuses local file storage — all three
are fine in development and unsafe in production, so startup blocks them deliberately.

Check it from your terminal:

```bash
curl https://hirehq-api.onrender.com/health
```

Look for `"status": "healthy"` and `"database": "up"`. The `providers` block reports what
is genuinely configured — it is telling you the truth about your deployment, so read it.

### Running without a worker (free tier)

If $7/month for the worker is not worth it yet, you can drop it. Delete the `worker`
service from `render.yaml`, set the web service to `plan: free`, and change **one** shared
variable:

```yaml
- key: USE_REDIS_QUEUE
  value: "false"
```

Background jobs then run **in-process inside the API** rather than on a queue. Be clear
about the trade:

- ✅ Résumés still parse and applications still get ATS scores.
- ❌ **Not durable.** A restart mid-job loses that job — and free instances restart
  whenever they wake from sleep.
- ❌ **No scheduled work at all.** Interview reminders, offer expiry and the five-minute
  mailbox sync live only in the worker. Mailboxes can still be synced on demand from the
  inbox UI.
- ❌ Free web services sleep after 15 minutes idle; the next visitor waits ~50 s.

The API reports this honestly — `is_durable=False` on the queue — rather than implying
jobs are safe.

---

## Step 7 — Deploy the frontend on Vercel

1. [vercel.com/new](https://vercel.com/new) → **Import** your `hirehq` repository.
2. Configure:

   | Setting | Value |
   | --- | --- |
   | Framework Preset | Next.js *(auto-detected)* |
   | **Root Directory** | **`frontend`** ← click *Edit* and set this |
   | Build & Install commands | leave default — `frontend/vercel.json` pins them |

3. Expand **Environment Variables** and add **one**, ticked for **Production, Preview and
   Development**:

   | Name | Value |
   | --- | --- |
   | `NEXT_PUBLIC_API_URL` | `https://hirehq-api.onrender.com/api/v1` |

   The **`/api/v1` suffix is required** — the client appends paths straight onto it.

4. **Deploy**, then copy the resulting `https://hirehq-<hash>.vercel.app`.

### If the build fails complaining about `NEXT_PUBLIC_API_URL`

That is intentional, and the message says which of three problems you have: unset, points
at `localhost`, or uses `http://`.

`NEXT_PUBLIC_*` values are **compiled into the JavaScript bundle at build time**. A wrong
value cannot be corrected afterwards by editing an environment variable — the deployed
bundle would keep calling the wrong host and fail in every visitor's browser, with nothing
in your server logs to show for it. The build refuses rather than shipping that.

**Corollary: changing the API URL later needs a redeploy, not just an env var edit.**

---

## Step 8 — Close the CORS loop

Two values on the backend must now become the real Vercel URL. Until they do, the site
loads but every request fails.

Render → **Env Groups** → `hirehq-shared` → edit:

```env
FRONTEND_BASE_URL=https://hirehq-<hash>.vercel.app
CORS_ORIGINS=https://hirehq-<hash>.vercel.app
```

Editing the group updates **both** services at once — which is the point of the group.
`FRONTEND_BASE_URL` is what builds the links inside offer emails, assessment invitations
and password resets, and the worker sends those, so both genuinely need it.

Rules that catch people out:

- The origin must match **exactly**: scheme included, **no trailing slash**.
- `CORS_ORIGINS` is comma-separated. Add a custom domain when you have one:
  `https://hirehq.vercel.app,https://careers.yourcompany.com`
- **Vercel preview deployments get generated URLs** not in this list, so previews cannot
  reach the API. That is the safe default; add specific preview URLs if you need them.

Render redeploys both services automatically when the env group changes. Wait for both to
go green.

---

## Step 9 — Verify the live deployment

In order — each step depends on the one before.

**1. API reachable and configured as intended:**

```bash
curl https://hirehq-api.onrender.com/health
```

**2. CORS genuinely allows your Vercel origin.** This is the most common failure, and the
terminal answers it far faster than guessing in a browser:

```bash
curl -sI -X OPTIONS \
  https://hirehq-api.onrender.com/api/v1/auth/login \
  -H "Origin: https://hirehq-<hash>.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  | grep -i "access-control-allow-origin"
```

Your Vercel URL must be echoed back. **No output means CORS is wrong** — return to step 8
and check for a trailing slash or `http` vs `https`.

Then in the browser:

**3.** Open the Vercel URL. The public job board renders. Empty is correct — no jobs yet.

**4.** DevTools → Network, then register at `/register`. Watch `/api/v1/auth/register`.
A CORS failure shows here as a *failed* request with **no status code at all**.

**5.** After signing in, open `/recruiter/dashboard` and check the badge beside the title.
It reads **Live** only when the SSE stream is genuinely open. "Connecting" means retrying;
"Not live" means refused.

**6.** As a super admin, open `/admin/dashboard`. The **provider configuration** panel
reports what is really wired up. A warning icon means that provider runs in a local or
unconfigured mode, and the product will say so to users rather than pretending. On a fresh
deployment expect warnings on AI and Email; storage should read durable.

**7.** End to end — the test that exercises the worker too:

- Create a job and publish it
- Apply from the public page in a private window, with a real PDF or DOCX
- In the recruiter pipeline the application appears within seconds, and the ATS score
  fills in shortly after

If the application appears but **the score never does**, the worker is not running or
cannot reach Redis. Check the worker's logs.

---

## Step 10 — Create your first account

**Do not run the demo seed on a real deployment** — it creates accounts whose passwords
are published in this repository. `python -m app.db.seed` takes only `--reset` and always
builds the full demo dataset, so it is not the tool for this.

Register through the UI at `/register` — self-registration always produces a **candidate**,
by design, since a public signup form must never be able to mint an administrator — then
promote that one account with the built-in tool:

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://..." .venv/Scripts/python -m app.db.promote you@example.com
```

PowerShell needs the variable set separately:

```powershell
$env:DATABASE_URL="postgresql+asyncpg://..."
.venv\Scripts\python -m app.db.promote you@example.com
```

It is idempotent, and `--role` grants something other than `SUPER_ADMIN`:

```bash
python -m app.db.promote someone@example.com --role COMPANY_ADMIN
```

Sign out and back in — your existing token still carries the old permissions — then create
your company from `/admin/companies`.

---

## Optional extras

All optional. Without each, the product **says so** rather than pretending — that is the
design, not a gap.

### Email (recommended — several flows are inert without it)

Without SMTP, password resets, verification links, interview invitations and offer emails
are recorded but never delivered, and the UI reports "Not sent". Use Resend, Postmark,
SendGrid or Mailgun, then add to the **`hirehq-shared` env group** so both services get it:

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USERNAME=resend
SMTP_PASSWORD=<your api key>
SMTP_USE_TLS=true
EMAIL_FROM_ADDRESS=no-reply@yourdomain.com
EMAIL_FROM_NAME=Your Company
```

Verify your sending domain with the provider first, or recipients silently drop the mail.

### Real AI

The default `heuristic` engine does real parsing, extraction and scoring with no network
call. It is not a language model and is never presented as one. To enable Claude, add to
the shared group:

```env
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-...
AI_MODEL=claude-opus-5
```

### Calendar and mailbox sync

Both use one Google or Microsoft OAuth app. In the Google Cloud Console create OAuth
credentials and register **both** redirect URIs against your Render domain:

```
https://hirehq-api.onrender.com/api/v1/calendar/callback
https://hirehq-api.onrender.com/api/v1/emails/accounts/callback
```

Then, in the shared group:

```env
CALENDAR_PROVIDER=google
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://hirehq-api.onrender.com/api/v1/calendar/callback
```

Mailbox scopes are read-only (`gmail.readonly`): HireHQ imports replies and never sends
from, deletes from, or modifies a personal mailbox.

### Custom domain

1. Vercel → project → **Settings → Domains** → add `careers.yourcompany.com` and set the
   CNAME at your DNS provider.
2. **Add the new origin to `CORS_ORIGINS` and `FRONTEND_BASE_URL`** in the Render env
   group. Skipping this is the usual reason a custom domain appears to break the app.

For the API on a subdomain: Render → service → **Settings → Custom Domains**, then update
`NEXT_PUBLIC_API_URL` on Vercel **and redeploy the frontend**.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Every request fails, **no HTTP status** in the network tab | CORS. `CORS_ORIGINS` does not exactly match the Vercel origin — check trailing slash and `https`. Use the `curl -X OPTIONS` check in step 9. |
| Requests go to `localhost:8000` | `NEXT_PUBLIC_API_URL` was wrong **at build time**. Fix it and **redeploy** — editing the variable alone changes nothing. |
| Vercel build fails: `NEXT_PUBLIC_API_URL is not set` | Working as intended. Set it in Vercel → Settings → Environment Variables, then redeploy. |
| Service exits: `JWT_SECRET must be set to a strong value` | The env group is not attached, or was overridden. Confirm both services list `hirehq-shared`. |
| Service exits: `STORAGE_PROVIDER=local is a development-only backend` | The storage variables did not reach the service. Check the env group. |
| `TypeError: connect() got an unexpected keyword argument 'sslmode'` | `?sslmode=require` is still on `DATABASE_URL`. Remove it (step 2). |
| `relation "users" does not exist` | Migrations never ran. Step 5. |
| Uploads fail with `NotImplemented` or a 400 from storage | R2 with `STORAGE_SERVER_SIDE_ENCRYPTION=AES256`. It must be empty for R2 (step 4). |
| Résumés upload but never parse; no ATS score | Worker not running, or it cannot reach Redis. Check worker logs; confirm `rediss://` and that `USE_REDIS_QUEUE=true` reaches **both** services. |
| Emails never arrive; UI says "Not sent" | No SMTP configured. That message is accurate — see [Email](#email-recommended--several-flows-are-inert-without-it). |
| Live badge stuck on "Not live" | The SSE stream was refused. Usually CORS; occasionally a proxy buffering `text/event-stream`. |
| First request after a quiet period takes ~50 s | A free Render instance woke from sleep. Upgrade to Starter, or accept it. |
| First request is slow but Render is on Starter | Neon's free tier scaled to zero. Expected. |

---

## Appendix — why the backend does not go on Vercel

Less a limitation of Vercel than a mismatch with what this backend does:

- **Server-sent events need a long-lived connection.** Vercel functions have an execution
  ceiling; the stream would be cut mid-flight and reconnect in a loop.
- **The ARQ worker is a persistent process** polling a queue and running cron jobs. There
  is nothing for a request-scoped function to hang that on.
- **Connection pooling.** SQLAlchemy's async pool assumes a process that outlives a
  request. Serverless invocations would exhaust Postgres connections without an external
  pooler.
- **Startup work.** The app bootstraps roles and permissions and resolves every provider
  at boot, deliberately, so a misconfiguration surfaces on deploy rather than during the
  first candidate application at 2am. Paying that on every cold start would be wasteful.

Splitting the frontend and API across two hosts costs nothing in capability — the browser
reaches the API directly either way.
