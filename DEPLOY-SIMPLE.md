# Putting HireHQ online — the simple version

No jargon. Follow the parts in order. Anything you must copy down is marked
**📋 COPY THIS**.

If you want the technical version instead, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## First — what are we actually doing?

Right now HireHQ only runs on your computer. To put it on the internet, you rent five
free/cheap services. Think of it like opening a shop:

| Think of it as | Real name | What it does |
| --- | --- | --- |
| 🏪 **The shop front** | Vercel | The pages people see and click |
| 👨‍🍳 **The kitchen** | Render | Does the actual work behind the scenes |
| 🗄️ **The filing cabinet** | Neon | Remembers everything (jobs, people, applications) |
| 📋 **The job list** | Upstash | A to-do list for slow tasks |
| 📦 **The storeroom** | Cloudflare R2 | Holds the CV files people upload |

They're separate because each one is good at a different thing. You'll set them up one at
a time and then tell them about each other at the end.

**Time needed:** about 45 minutes.
**Cost:** $14/month, or free if you accept some limits (explained in Part 6).

---

## Before you start: open a notepad

You'll collect 8 pieces of information as you go. Open Notepad (or any notes app) and
keep it open. You'll paste things in as you find them.

Copy this template into your notepad now:

```
1. Database address    = 
2. Job list address    = 
3. Storeroom address   = 
4. Storeroom username  = 
5. Storeroom password  = 
6. Kitchen web address = 
7. Shop web address    = 
```

Don't worry about what these mean yet. Just fill them in as you go.

---

# PART 1 — Put your code on the internet

Websites can't be built from your laptop. Your code needs to live somewhere the services
can read it. That place is **GitHub**.

### 1.1 — Make a GitHub account

Go to [github.com](https://github.com) and sign up. It's free.

### 1.2 — Prepare your code

Open a terminal in your HireHQ folder and type these lines **one at a time**, pressing
Enter after each:

```bash
git init
git add .
git commit -m "HireHQ"
git branch -M main
```

### 1.3 — Safety check (important!)

Your project has files with passwords in them. They must **not** go online. Run this:

```bash
git ls-files | grep -E "\.env$|\.env\.local$|\.db$"
```

👉 **You should see nothing at all.** Blank. Empty.

If it *does* print a filename, stop and tell me — don't continue.

### 1.4 — Create the online copy

1. Go to [github.com/new](https://github.com/new)
2. **Repository name:** `hirehq`
3. Leave everything else alone. **Don't** tick "Add a README file".
4. Click **Create repository**

GitHub now shows you a page with commands. Ignore it and use these instead — replace
`YOUR-USERNAME` with your actual GitHub username:

```bash
git remote add origin https://github.com/YOUR-USERNAME/hirehq.git
git push -u origin main
```

Refresh the GitHub page. You should see your files. ✅

---

# PART 2 — The filing cabinet (remembers everything)

### 2.1 — Sign up

Go to [neon.tech](https://neon.tech) → **Sign up** (use your GitHub account, it's quicker).

### 2.2 — Create it

1. Click **New Project**
2. **Name:** `hirehq`
3. **Region:** pick **US East (Ohio)** — remember this, you'll match it later
4. Click **Create**

### 2.3 — Get the address 📋 **COPY THIS**

On the page that appears, find the **Connection string** box and copy it. It looks like a
long messy line:

```
postgresql://neondb_owner:npg_AbC123@ep-cool-mud-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
```

### 2.4 — Now fix it (this bit matters!)

That address won't work as-is. You need to make **two small edits**. Paste it into your
notepad and change it:

**Edit 1** — at the very start, change:

```
postgresql://
```

into:

```
postgresql+asyncpg://
```

*(you're just adding `+asyncpg` after the word postgresql)*

**Edit 2** — at the very end, delete this bit:

```
?sslmode=require
```

*(delete the question mark and everything after it)*

**Result** — save this as **#1 Database address** in your notepad:

```
postgresql+asyncpg://neondb_owner:npg_AbC123@ep-cool-mud-12345.us-east-2.aws.neon.tech/neondb
```

> **Why?** The app talks to the database in a specific way, and those two edits tell it
> which way. Skip them and you'll get a confusing error later. It's still secure — that's
> handled automatically.

---

# PART 3 — The job list

When someone uploads a CV, reading it takes a few seconds. Rather than make them wait,
HireHQ writes "read this CV" on a list and gets on with it. This is that list.

### 3.1 — Sign up

Go to [upstash.com](https://upstash.com) → **Sign up**.

### 3.2 — Create it

1. Click **Create Database**
2. **Name:** `hirehq`
3. **Type:** Regional
4. **Region:** pick the one closest to **US East** (to match Part 2)
5. ⚠️ Find the **Eviction** setting and make sure it is **OFF / disabled**
6. Click **Create**

> **Why does Eviction matter?** "Eviction" means "throw away old items when full". If it
> throws away a job, someone's CV silently never gets read. Leave it off.

### 3.3 — Get the address 📋 **COPY THIS**

Scroll down the database page. You want the one that starts with `rediss://` — note the
**two S's**.

Save as **#2 Job list address**:

```
rediss://default:AXbCdEf123@fine-cat-12345.upstash.io:6379
```

⚠️ There are several addresses on that page. You want the **TCP / Redis** one that begins
`rediss://`. **Not** the one starting with `https://`.

---

# PART 4 — The storeroom (holds CV files)

### 4.1 — Sign up

Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **Sign up**.

### 4.2 — Create the storeroom

1. In the left menu click **R2**
2. Click **Create bucket**
3. **Name:** `hirehq`
4. Click **Create bucket**
5. ⚠️ **Do NOT turn on public access.** CVs are private. HireHQ hands out temporary links
   instead.

### 4.3 — Get the keys 📋 **COPY THESE**

1. Still in **R2**, click **Manage R2 API Tokens** (right side of the page)
2. Click **Create API Token**
3. **Permissions:** choose **Object Read & Write**
4. **Specify bucket:** choose your `hirehq` bucket
5. Click **Create API Token**

You now get three things. Save all three:

- **#3 Storeroom address** — looks like `https://a1b2c3d4.r2.cloudflarestorage.com`
- **#4 Storeroom username** — labelled *Access Key ID*
- **#5 Storeroom password** — labelled *Secret Access Key*

⚠️ **The password is shown only once.** Copy it now. If you lose it, delete the token and
make a new one.

---

# PART 5 — Set up the filing cabinet's drawers

Your filing cabinet is empty — it doesn't have drawers or folders yet. This step creates
them. It only needs doing once.

Open a terminal in your HireHQ folder and run this. **Replace the address in quotes with
your #1 from the notepad.**

**On Windows — PowerShell** (the blue terminal, the usual one):

```powershell
cd backend
$env:DATABASE_URL="PUT-YOUR-#1-ADDRESS-HERE"
.venv\Scripts\python -m alembic upgrade head
```

**On Windows — Git Bash, or Mac / Linux:**

```bash
cd backend
DATABASE_URL="PUT-YOUR-#1-ADDRESS-HERE" .venv/Scripts/python -m alembic upgrade head
```

*(Mac and Linux: use `.venv/bin/python` instead of `.venv/Scripts/python`.)*

> **Which terminal am I in?** If the prompt starts with `PS C:\>` you're in PowerShell —
> use the first one. Keep that window open; you'll reuse the address in Part 10.

### Did it work?

The last line should say:

```
Running upgrade  -> d8a311cc31fa, initial schema
```

✅ That's it. Your database now has **57 tables** (drawers) ready.

❌ **If you see** `unexpected keyword argument 'sslmode'` — you forgot Edit 2 in Part 2.4.
Remove `?sslmode=require` from the end of your address and try again.

---

# PART 6 — The kitchen (does the work)

### 6.1 — Decide: $14/month or free?

Read this before continuing:

| | Paid ($14/mo) | Free |
| --- | --- | --- |
| Site always awake | ✅ Yes | ❌ Sleeps after 15 min. First visitor waits ~50 seconds |
| CVs get read automatically | ✅ Yes | ✅ Yes |
| Reminder emails send automatically | ✅ Yes | ❌ No |
| Checks for candidate replies | ✅ Every 5 min | ❌ Only when you click "Sync" |
| Safe if it restarts mid-job | ✅ Yes | ❌ That job is lost |

**Just testing?** Free is fine.
**Real users?** Pay the $14.

The steps below are for the **paid** version. To go free, see
[6.6 Going free](#66--going-free) at the end of this part.

### 6.2 — Sign up

Go to [render.com](https://render.com) → **Sign up** with GitHub.

### 6.3 — Create both services at once

Your project has a file that tells Render exactly what to build, so you don't have to
click through settings.

1. Click **New +** (top right) → **Blueprint**
2. Click **Connect GitHub** and allow access to your `hirehq` repository
3. Select the `hirehq` repository
4. Give it the name `hirehq`

Render reads the instructions and says it will create **two things**:

- `hirehq-api` — the kitchen
- `hirehq-worker` — the helper that does slow jobs

### 6.4 — Fill in the blanks

Render now asks you for the values you collected. Fill them in from your notepad:

| It asks for | Paste your |
| --- | --- |
| `DATABASE_URL` | #1 Database address |
| `REDIS_URL` | #2 Job list address |
| `STORAGE_ENDPOINT` | #3 Storeroom address |
| `STORAGE_ACCESS_KEY` | #4 Storeroom username |
| `STORAGE_SECRET_KEY` | #5 Storeroom password |
| `BACKEND_BASE_URL` | type `https://hirehq-api.onrender.com` |
| `FRONTEND_BASE_URL` | type `https://temporary.vercel.app` |
| `CORS_ORIGINS` | type `https://temporary.vercel.app` |

> **Why the fake "temporary" ones?** Your shop front doesn't exist yet, so you don't know
> its address. You'll come back and fix these in Part 8. Nothing breaks in the meantime.

Click **Apply**.

### 6.5 — Wait, then check

The first build takes **5–10 minutes**. Go make tea.

When both services show a green dot:

1. Click on **hirehq-api**
2. At the top of its page you'll see its web address, something like
   `https://hirehq-api.onrender.com`

📋 Save that as **#6 Kitchen web address**.

⚠️ If Render gave it a different name (like `hirehq-api-a1b2`), open **hirehq-api** →
**Environment** and correct `BACKEND_BASE_URL` to match.

**Test it.** Paste your #6 address into a browser and add `/health` on the end:

```
https://hirehq-api.onrender.com/health
```

You should see text containing `"status": "healthy"` and `"database": "up"`. ✅

> **Seeing warnings in the logs about AI and email?** That's normal and correct. It's the
> app telling you those aren't set up yet, rather than pretending they are. You can add
> them later.

### 6.6 — Going free

Only if you chose free. Open `render.yaml` in your project, and:

1. Find `value: "true"` under `USE_REDIS_QUEUE` and change it to `value: "false"`
2. Change both lines that say `plan: starter` to `plan: free`
3. Delete the whole `hirehq-worker` section at the bottom (from `- type: worker` down)
4. Save, then run: `git add . && git commit -m "free tier" && git push`

---

# PART 7 — The shop front (what people see)

### 7.1 — Sign up

Go to [vercel.com](https://vercel.com) → **Sign up** with GitHub.

### 7.2 — Import your project

1. Click **Add New...** → **Project**
2. Find `hirehq` in the list → click **Import**

### 7.3 — Change ONE setting (don't miss this)

Look for **Root Directory**. It probably says `./`.

Click **Edit** next to it, and choose the **`frontend`** folder.

⚠️ Miss this and the build fails.

### 7.4 — Add the kitchen's address

1. Click to expand **Environment Variables**
2. Add one:

   - **Name:** `NEXT_PUBLIC_API_URL`
   - **Value:** your **#6 Kitchen web address**, with `/api/v1` added on the end

   So if #6 was `https://hirehq-api.onrender.com`, you type:

   ```
   https://hirehq-api.onrender.com/api/v1
   ```

⚠️ The `/api/v1` on the end is required. Don't leave it off.

### 7.5 — Deploy

Click **Deploy**. Wait 2–3 minutes.

You'll get an address like `https://hirehq-abc123.vercel.app`.

📋 Save it as **#7 Shop web address**.

### If the build fails with a red error about `NEXT_PUBLIC_API_URL`

Good news — that's the app protecting you, not a bug. It means the address was missing or
wrong. The error text says which. Fix it in **Settings → Environment Variables**, then
click **Redeploy**.

> ⚠️ **Remember this:** if you ever change the kitchen's address later, changing the
> setting isn't enough — you must click **Redeploy** too. The address gets baked into the
> site when it's built.

---

# PART 8 — Introduce the shop to the kitchen

Right now your shop front loads, but nothing works. The kitchen doesn't know the shop
exists, so it refuses to talk to it. (This is a security feature — otherwise any website
could talk to your kitchen.)

Let's fix that:

1. Go back to [Render](https://dashboard.render.com)
2. Click your **hirehq-api** service → **Environment** tab
3. Find `FRONTEND_BASE_URL` and change `https://temporary.vercel.app` to your **#7 Shop
   web address**
4. Find `CORS_ORIGINS` and change it to the same **#7** address
5. Click **Save Changes**

The helper service copies `FRONTEND_BASE_URL` from the kitchen automatically, so you only
edit it in this one place.

⚠️ **Type it exactly.** No slash `/` on the end. Must start with `https://` not `http://`.

✅ Right: `https://hirehq-abc123.vercel.app`
❌ Wrong: `https://hirehq-abc123.vercel.app/`
❌ Wrong: `http://hirehq-abc123.vercel.app`

Render will restart both services automatically. Wait for green dots (about 2 minutes).

---

# PART 9 — Check everything works

Do these in order.

### 9.1 — Open your site

Go to your **#7 Shop web address** in a browser.

You should see the HireHQ homepage. The jobs list will be empty — that's correct, you
haven't made any jobs yet.

### 9.2 — Make an account

1. Click **Register** / **Create account**
2. Fill it in and submit

**Did it work?** ✅ Great, the shop and kitchen are talking.

**Did nothing happen, or you got a vague error?** That's almost always Part 8. Go back and
check the address for a stray `/` on the end.

### 9.3 — Sign in

Sign in with the account you just made.

You'll land on a candidate page — that's expected. Everyone starts as a candidate. Part 10
makes you the boss.

---

# PART 10 — Make yourself the boss

New accounts are always job-seekers. You need to promote yourself to admin.

⚠️ **Don't use the demo data command.** It creates accounts whose passwords are published
in this project's files.

There's a small tool built in for exactly this. Run it in your terminal, changing **two
things**: the address (your #1) and your email address.

**On Windows — PowerShell** (the blue terminal):

```powershell
cd backend
$env:DATABASE_URL="PUT-YOUR-#1-ADDRESS-HERE"
.venv\Scripts\python -m app.db.promote you@example.com
```

**On Windows — Git Bash, or Mac / Linux:**

```bash
cd backend
DATABASE_URL="PUT-YOUR-#1-ADDRESS-HERE" .venv/Scripts/python -m app.db.promote you@example.com
```

*(Mac and Linux: use `.venv/bin/python` instead of `.venv/Scripts/python`.)*

It should print:

```
Done. you@example.com is now SUPER_ADMIN.
Sign out and sign back in - your current session still has the old access.
```

If it says **"No account found"**, you haven't registered on the site yet — do Part 9.2
first. Running it twice is safe; it just says there's nothing to do.

**Now sign out and sign back in.** (Your login "pass" still says candidate until you do.)

You're now an admin. 🎉

---

# PART 11 — Try the whole thing

Let's prove it really works end to end:

1. Go to **Companies** and create your company
2. Go to **Jobs** → create a job → **Publish** it
3. Open your site in a **private/incognito window**
4. Find the job and apply — upload a real PDF or Word CV
5. Back in your normal window, open **Pipeline**

Within a few seconds the application appears. A few seconds later a **match score** shows
up next to it.

**Score never appears?** The helper (worker) isn't running. On Render, open
**hirehq-worker** and read its logs.

---

# Things that commonly go wrong

| What you see | What's wrong | Fix |
| --- | --- | --- |
| `JWT_SECRET must be set to a strong value` | Render didn't pass ANY settings to the kitchen | Open **hirehq-api** → **Environment**. If it's nearly empty, see the box below this table |
| Site loads but nothing works. Errors have no number. | The kitchen doesn't recognise the shop. | Part 8 — check for a `/` on the end |
| `unexpected keyword argument 'sslmode'` | Database address not edited | Part 2.4 — remove `?sslmode=require` |
| `relation "users" does not exist` | Filing cabinet has no drawers | Part 5 |
| Vercel build fails, mentions `NEXT_PUBLIC_API_URL` | Kitchen address missing or wrong | Part 7.4, then **Redeploy** |
| Site tries to reach `localhost` | Address was wrong when it was built | Fix it, then **Redeploy** (not just save) |
| CVs upload but never get read | Helper not running, or job list unreachable | Check `hirehq-worker` logs on Render |
| Upload fails with a storage error | Storeroom setting wrong for Cloudflare | In Render, `STORAGE_SERVER_SIDE_ENCRYPTION` must be **empty** |
| No emails ever arrive; it says "Not sent" | Email isn't set up | Correct — it's being honest. See below |
| First visit takes ~50 seconds | Free service was asleep | Normal on free. Upgrade or accept it |

### If the kitchen says "JWT_SECRET must be set to a strong value"

This message is misleading. It doesn't mean your secret is weak — it means Render gave the
kitchen **no settings at all**, so it fell back to the built-in placeholder.

**Check:** Render → **hirehq-api** → **Environment** tab. Nearly empty? That's the problem.

**Fix:** add them by hand. On that same Environment tab click **Add Environment Variable**
for each row below. First, make a secret by running this on your computer:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Name | Value |
| --- | --- |
| `JWT_SECRET` | the long string you just generated |
| `DATABASE_URL` | your **#1** |
| `REDIS_URL` | your **#2** |
| `STORAGE_ENDPOINT` | your **#3** |
| `STORAGE_ACCESS_KEY` | your **#4** |
| `STORAGE_SECRET_KEY` | your **#5** |
| `USE_REDIS_QUEUE` | `true` |
| `USE_REDIS_CACHE` | `true` |
| `STORAGE_PROVIDER` | `s3` |
| `STORAGE_BUCKET` | `hirehq` |
| `STORAGE_REGION` | `auto` |
| `STORAGE_SERVER_SIDE_ENCRYPTION` | *leave the value box empty* |
| `DEBUG` | `false` |
| `WEB_CONCURRENCY` | `2` |
| `BACKEND_BASE_URL` | your **#6** |
| `FRONTEND_BASE_URL` | your **#7** (or `https://temporary.vercel.app` for now) |
| `CORS_ORIGINS` | same as `FRONTEND_BASE_URL` |

Click **Save Changes**. Render restarts it automatically.

Do the same for **hirehq-worker**, but skip `CORS_ORIGINS` and `WEB_CONCURRENCY`.

⚠️ The worker's `JWT_SECRET` must be the **exact same string** as the kitchen's. Copy and
paste it — don't generate a second one.

---

# Optional — turning on extra features

Everything below is optional. Without them, HireHQ **tells you** they're off rather than
pretending they work.

To add any of these: Render → **Env Groups** → **hirehq-config** → add the settings →
**Save**. Both services pick them up.

### Sending real emails

Without this, password resets and interview invites are written down but never sent.

Sign up at [resend.com](https://resend.com) (free tier available), verify your domain,
then add:

```
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USERNAME=resend
SMTP_PASSWORD=your-key-from-resend
SMTP_USE_TLS=true
EMAIL_FROM_ADDRESS=no-reply@yourdomain.com
```

### Smarter AI

HireHQ already reads CVs and scores them properly without this — it uses fixed rules, not
guesswork, and never claims to be more than that. For AI-written summaries and the chat
assistant, add:

```
AI_PROVIDER=anthropic
AI_API_KEY=your-key-from-anthropic
```

### Your own web address (like careers.yourcompany.com)

1. Vercel → your project → **Settings** → **Domains** → add it, and follow the DNS steps
2. ⚠️ Then go to Render → **hirehq-api** → **Environment** and add the new address to
   **both** `CORS_ORIGINS` and `FRONTEND_BASE_URL`, separated by a comma:

   ```
   https://hirehq-abc123.vercel.app,https://careers.yourcompany.com
   ```

   Forgetting this is the usual reason a custom domain "breaks" the site.
