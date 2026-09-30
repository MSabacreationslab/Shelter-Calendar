# Shelter Volunteer Scheduler — Build Spec

This spec is the source of truth for building the app. It replaces `shelter-app-project-plan.md` (kept outside the repo). Phase numbers match that plan, plus a new Phase 0.

- **(proposed)** marks a default Claude chose where the plan said nothing. Confirm or change it in review.
- **(Q#)** points to an open question in §11. Each question names the phase it blocks.
- If a decision changes during a phase, update this file in that phase's PR.

---

## 1. Overview

**Client:** Humane Society of Madison County, West Jefferson, Ohio.

**What it does:** once the shelter's paperwork is done, staff add each volunteer to the app, and volunteers sign up for the shifts they're trained for. Staff run the schedule, track training, and get a weekly picture of who's coming.

**Who uses it:** volunteers and staff, many aged 65 or older, and some not confident with phones or computers. **When a feature and simplicity pull in different directions, simplicity wins.** Anything that confuses a first-time user on a phone is a bug.

**Scale:** a pilot of 10 volunteers and 4 staff, growing to perhaps 50–100 volunteers (proposed assumption). Nothing here needs to scale beyond that.

**Devices:** people's own phones (iPhone and Android), home computers, and the shelter's iPad (used for check-in in V2).

**Out of scope indefinitely:** push notifications, and donor/adopter CRM or categorization.
**Not in V1 (see §6, V2):** hour tracking, volunteer availability, the Petfinder birthday photo, QR badges, and a custom domain. Online applications and approvals are a possible future feature (Q16).

---

## 2. Tech Stack & Hosting

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | Already in CI |
| Framework | **Django 5.2 LTS** | Supported until April 2028; fits the existing `Django>=5.0,<6.0` pin |
| Pages | Server-rendered Django templates, plain CSS with design tokens, small vanilla JS only as an enhancement | No build step and fewer moving parts. Fast on old phones and friendly to screen readers. **Every core flow works with JavaScript turned off.** |
| Database | **PostgreSQL 16+ everywhere** (local, CI, test site, pilot) | Double-booking is blocked by a Postgres exclusion constraint (`django.contrib.postgres`). SQLite can't do that, so there's no SQLite fallback. |
| Packages | `psycopg[binary]` (v3, replacing `psycopg2-binary`), `dj-database-url`, `whitenoise`, `gunicorn`, `holidays`; dev: `pytest-django`, `factory-boy`, `ruff` | Keep the list short. A new dependency needs a one-line reason in its PR. |
| Email | Django SMTP backend. Test site: a dedicated Gmail account with an app password, as Pantry Sprite does. Local: console backend. Tests: locmem backend. | $0 |
| Time zone | `America/New_York`, `USE_TZ = True` | Shelter is in Ohio |

### Hosting

**Test site: free.** Django runs on a **Render free web service** and Postgres is a **Supabase free project**.

- **Why not Cloudflare Pages:** it only serves static files and can't run a Django server. Pantry Sprite works there because it has no server of its own (Supabase is its whole backend). Here Supabase is used **only as a Postgres database**, not for its auth, APIs or storage.
- **Caveats:**
  - Render's free tier sleeps after 15 minutes idle and takes 30–60 seconds to wake. That's fine for testing but **not acceptable for the pilot**.
  - Supabase free pauses a project after 7 days without activity (one click to restore) and allows 2 active projects. Pantry Sprite uses one.
- **Connecting:** use Supabase's **session pooler** connection string, which works over IPv4. The direct connection string is IPv6-only and many hosts can't reach it.
- **Deploys:** a `render.yaml` blueprint in the repo. The start command runs `migrate` and then `gunicorn`. Auto-deploy from `main`.

**Pilot: Railway**, as the plan says. It's always on with no cold starts. The pilot database is Railway Postgres with daily backups (decided, Q15).

**Scheduled jobs** (weekly digest, reminders; Phase 7 onward) are Django management commands. Railway cron runs them on the pilot; on the test site they're run by hand (decided, Q13). Render's free tier has no cron.

### CI (`.github/workflows/ci.yml`)
- One job, pip cache, no matrix.
- **Triggers:** pull requests (to any base branch, so stacked phase PRs are checked too) and pushes to `main`. This drops the current "push to every branch" trigger, which runs everything twice.
- **Steps:**
  1. `ruff check` and `ruff format --check`
  2. `manage.py check`
  3. `manage.py makemigrations --check --dry-run`
  4. `pytest` against a Postgres service container
  5. Upload the JUnit XML, even on failure
- The workflow keeps the name `CI` because `self-heal.yml` listens for it.
- The job keeps the id `build`: the `protect-main` ruleset requires a status check named `build`. Renaming the job would leave every PR unmergeable.
- No tutorial-style comments in workflow files.

### Self-heal pipeline: on hold
`self-heal.yml` stays in the repo, but **no new pipeline work happens until the pilot launches (Phase 9)** unless Mike asks for it. Turning the workflow on or off in GitHub is Mike's call. If it runs, the Auto-Fix and Novel Failure rules in `CLAUDE.md` still apply.

---

## 3. Roles & Permissions

### Roles (decided 2026-09-29, Q1)
| Role | Who | In one line |
|---|---|---|
| **Volunteer** | Approved volunteers | Signs up for and cancels their own shifts, and keeps their own contact details current |
| **Staff** | The shelter's leads. At launch: the **Shelter Lead**, the **Volunteer Lead** and the **Volunteer Lead's Assistant**. Staff can add more. | Runs everything in the app's staff screens. **All staff have the same powers**; the job title is only a label. |
| **Admin** | Mike only | Everything staff can do, plus app settings and the Django admin. Mike is the only person with backend access (database, code, deploys). |

- Each staff account has a `job_title` shown next to their name ("Volunteer Lead").
- **Admin accounts can only be created from the command line** (`create_admin`), so nobody can make themselves or anyone else an Admin in the app. Staff can't edit, reset or deactivate an Admin account.

### Change log (decided)
Every change is recorded: who made it, what changed, and when. That includes:
- shift assignments, sign-ups and cancellations (a volunteer's own included)
- PIN resets, setup links sent, accounts created or deactivated
- volunteers added, and training records
- shift and schedule edits, and settings changes
- hours changes (V2)

All staff and the Admin can read the change log and filter it by person and date. Each person's page shows their recent changes. The log is append-only: nobody can edit or delete it in the app.

### Safeguards
- **Nobody** can see a PIN, sign in as someone else, or act on a volunteer's behalf. "View as volunteer" is read-only.
- Nothing that forms a person's history can be deleted in the app: training records, past shifts and change-log entries. Records are deactivated, cancelled or voided instead.

### Capability map
Code checks **capabilities**, never role names. Role names appear in exactly one place: the map in `accounts/permissions.py`. If staff ever need different levels, only the map changes.

| Capability | Volunteer | Staff | Admin |
|---|:-:|:-:|:-:|
| `view_own_schedule`, `edit_own_contact`, `sign_up_self`, `cancel_own_signup` | ✓ | ✓¹ | ✓¹ |
| `view_dashboard`, `view_full_schedule`, `view_contacts`, `view_as_volunteer`, `view_change_log` | – | ✓ | ✓ |
| `manage_shifts`, `assign_volunteers`, `manage_waitlist`, `record_training`, `manage_trainings` | – | ✓ | ✓ |
| `add_volunteers`, `edit_volunteers`, `reset_volunteer_pin`, `view_reports` | – | ✓ | ✓ |
| `manage_staff`: add staff, change job titles, deactivate staff, send a staff member a new PIN link (never an Admin account) | – | ✓ | ✓ |
| `edit_settings`, Django admin | – | – | ✓ |

¹ Staff and the Admin can sign up for shifts they're trained for, under the same eligibility rules as volunteers (decided, Q3).

### Rules
- Views declare their capability with a decorator or mixin, and templates check it with a template tag. **Every URL must declare a capability** (or `public` / `signed_in`).
- **Permission-matrix test** (guard rail, like Pantry Sprite's RLS guard):
  - For every URL pattern × every role (plus signed out), the response must be allowed or denied exactly as the map says.
  - The test **fails if any URL has no declared capability**. New pages can't slip through.
- **Object-level:** volunteers only ever touch their own signups, waitlist entries and profile. Tests must cover tampering with IDs in URLs and forms.
- Denied pages are friendly ("This page is for shelter staff.") with an error code, not a bare 403. Signed-out users are sent to sign in and then returned.
- The Django admin site lives at `/django-admin/`, is for the superuser (Mike) only, and is for emergencies. It's never part of a staff workflow.

---

## 4. Sign-in: Name + PIN

### The sign-in screen
Two large fields, **"Your name"** and **"PIN"**, and a big **Sign in** button.
- **Name matching:** case-insensitive, with extra spaces trimmed and collapsed.
- Each person has a unique **sign-in name** (`login_name`), which defaults to "First Last". If it's taken, staff add something when adding them (e.g. "Mary Smith B"). The welcome email states the sign-in name.

### PINs
- Everyone uses exactly **6 digits** (decided, Q2; the original plan said 4).
- Stored with Django's password hashing. **No one can see a PIN, and staff never choose one for someone else.**
- **Blocked PINs:**
  - all the same digit (000000, 111111…)
  - straight runs up or down (012345…456789, 987654…543210)
  - a repeated pair or triple (121212, 101010, 123123, 112233)
  - a short list of other common PINs: 123321, 111222, 147258, 159753, 102030
  - the last 6 digits of the person's own phone number
  - The error gives an example of a good choice: "Please pick a PIN that's harder to guess, like one without a pattern."
- **Entry fields:**
  - PIN fields use `inputmode="numeric"` and `autocomplete="current-password"`, or `"new-password"` when setting one.
  - A **Show PIN** toggle, because typing blind is hard.
  - Setting a PIN asks for it twice.

### Wrong PIN, lockouts
- The same message is shown whether or not the name exists: "That name and PIN don't match. Please try again."
- After 3 misses the page adds: "Forgot your PIN? Call the shelter at {phone}."
- **Lockouts (proposed):**
  - **5 wrong PINs for one account within 15 minutes:** that account can't sign in for 15 minutes. "Too many tries. For your safety, please wait 15 minutes, or call the shelter at {phone}."
  - **3 lockouts within 24 hours:** the account stays locked until staff send a new setup link.
  - **More than 20 failed sign-ins from one device (IP) within 15 minutes:** that device waits 15 minutes. This protects against guessing across many names.
- Counts come from a `LoginAttempt` table, not a cache, so they survive restarts and work across processes.
- Client IP comes from `REMOTE_ADDR`, or from the host's proxy header with a configured trusted-proxy count. A client-sent `X-Forwarded-For` is never trusted blindly.

### Sessions (proposed)
- **Volunteers:** stay signed in for **30 days**, and the clock resets on each visit.
- **Staff:** **12 hours**, because they can see everyone's contact details.
- **Sign out** is always visible in the header.
- Cookies are `Secure`, `HttpOnly` and `SameSite=Lax`.
- Setting a new PIN signs out that person's other sessions.

### Setup links (one-time, single-use, 1-week expiry)
- **Created by:** adding a volunteer or a staff account, **Reset PIN**, and **Resend invite**.
- **Token:** 32 random bytes, URL-safe. **Only its hash is stored.** Valid for **7 days** and used once. Creating a new link voids the person's older unused links.
- **Opening a link must not use it up.** Email link scanners prefetch links. The link is used when the person **submits** their new PIN, and a GET never changes anything.
- **Flow:** open link → "Welcome, Mary. Choose a 6-digit PIN." → enter it twice → signed in → Home. This also clears any lockout.
- **Expired or used link:** a friendly page ("This link has expired. Please call the shelter at {phone} and we'll send a new one.") with an error code.
- **Email is required** for every volunteer and staff member (decided, Q4: everyone has email).
- **No self-service "email me a new link".** Staff or the Admin reset PINs by sending a new setup link (decided, Q5).

---

## 5. Data Model

Apps: `core` (base templates, design tokens, error codes, settings, audit), `accounts`, `training`, `scheduling`. Later: `notifications` and `reports`.

All datetimes are timezone-aware. People and history are never hard-deleted in the app.

### core
- **`ShelterSettings`** (single row): `shelter_name`, `shelter_phone`, `shelter_email`, `self_cancel_hours` (default 24, decided Q9), `urgent_threshold_hours` (24 or 48, for the pilot A/B), `notify_emails` (the staff who get notification emails).
  - The waitlist maximum is fixed at **10** per the plan. It's a constant, not a setting.
- **`AuditEvent`** (shown on screen as the **change log**, §3; append-only, and `save()` refuses updates):
  - fields: `actor`, `action` (string key, e.g. `volunteer.added`), `target_user` (nullable), `target_repr` (text), `details` (JSON), `created_at`
  - indexed on `(target_user, created_at)`

### accounts
- **`User`** (custom `AUTH_USER_MODEL`, **created in Phase 0's first migration**, because Django can't switch later without pain):
  - `first_name`, `last_name`, `login_name`, `email`, `phone`
  - `role` (`volunteer` | `staff` | `admin`), `job_title` (staff only, e.g. "Volunteer Lead")
  - `status` (`active` | `inactive`)
  - `password` (the PIN hash), `avatar` (key or blank, meaning initials)
  - `last_login`, `date_joined`, `deactivated_at`
  - `is_superuser` / `is_staff` are for the Django admin only.
  - Constraints:
    - unique `Lower(login_name)`
    - check that `role` and `status` are valid
- **`VolunteerProfile`** (1:1 with User):
  - emergency contact: `emergency_contact_name`, `emergency_contact_phone`, `emergency_contact_relationship`
  - `skills` (M2M `Skill`)
  - `birthday_month`, `birthday_day` (optional; no year, proposed)
  - `no_training_eligible` (bool: may take shifts that need no training)
  - `staff_notes` (staff-only)
  - `added_by` (the staff member who added them)
- **`Skill`**: `name`, `active`. Staff tick skills when adding a volunteer. They're **informational only, never used for eligibility**. Starting list (decided, Q7): Dog walking, Cat enrichment, Dog kennel cleaning, Cat cage cleaning, Special events. Staff can add, rename and deactivate skills.
- **`SetupLink`**:
  - fields: `user`, `token_hash` (unique), `purpose` (`invite` | `reset`), `created_by`, `created_at`, `expires_at`, `used_at`, `voided_at`
  - valid = not used, not voided, not expired
- **`LoginAttempt`**:
  - fields: `name_entered` (normalized), `user` (nullable), `ip`, `succeeded`, `created_at`
  - indexed on `(user, created_at)` and `(ip, created_at)`
  - Pruned after 90 days by a management command.

### training
- **`TrainingType`**: `name`, `description`, `is_orientation` (a constraint allows at most one), `active`.
- **`TrainingNeed`**: `volunteer`, `training_type`, `created_by`, `created_at`, `resolved_at`. Unique on `(volunteer, training_type)` while unresolved.
- **`TrainingRecord`**:
  - fields: `volunteer`, `training_type`, `completed_on`, `trainer` (staff User), `signed_off_by` (the staff member who saved it), `session` (nullable FK to a training-kind `Shift`), `notes`, `created_at`
  - voiding: `voided_at`, `voided_by`, `void_reason`
  - Voided, never deleted.
- **Eligibility**, one function, `training.eligibility.can_take(user, shift)` (used everywhere):
  - The user is `active` and the shift is `scheduled` and in the future.
  - A **regular** shift with no required training needs `no_training_eligible`. Staff and the Admin always count as eligible for these.
  - A **regular** shift that requires training X needs a non-voided `TrainingRecord` for X.
  - A **training** shift (a session teaching X) needs an unresolved `TrainingNeed` for X, or `assign_volunteers` staff adding them.
- Saving an **orientation** record automatically sets `no_training_eligible = True` (proposed).

### scheduling
- **`TemplateWeek`**: `name` (e.g. "Regular week", "Summer"), `notes`.
- **`ShiftPattern`** (the recurrence rule):
  - `template_week` (nullable, so a pattern can stand alone), `title`, `weekday` (0–6), `start_time`, `end_time`
  - `capacity` (≥ 1), `kind` (`regular` | `training`), `required_training` (nullable), `teaches` (TrainingType, required when kind is training)
  - `every_n_weeks` (1 or 2), `anchor_date`, `active_from`, `active_until` (nullable), `notes`
- **`Shift`** (an independent, editable instance):
  - `pattern` (nullable, `SET_NULL`), `title`, `kind`, `teaches`, `required_training`
  - `starts_at`, `ends_at` (aware), `local_date` (set from `starts_at`, for calendar queries), `capacity`, `notes`
  - `status` (`scheduled` | `cancelled`), `cancel_reason`, `holiday_name` (blank if none), `edited_by_hand` (bool)
  - `created_by`, `created_at`
  - Constraints:
    - `ends_at > starts_at`
    - `capacity >= 1`
    - unique `(pattern, local_date)` when pattern is set, so filling the schedule twice never duplicates
- **`Signup`**:
  - `shift`, `volunteer`, `status` (`confirmed` | `cancelled`)
  - `period` (`DateTimeRangeField`, copied from the shift and kept in sync)
  - `created_by` (self or staff), `created_at`
  - cancellation: `cancelled_at`, `cancelled_by`, `cancel_reason`, `is_late_cancel`
  - Constraints:
    - unique `(shift, volunteer)` where `confirmed`, so a double tap can't sign someone up twice
    - **exclusion constraint:** `(volunteer WITH =, period WITH &&)` where `confirmed`. No one can hold two overlapping shifts, even under a race. Needs the `btree_gist` extension, added in a migration.
  - **Capacity** is enforced in the `sign_up()` service by locking the shift row (`select_for_update`) and counting confirmed signups inside the transaction.
- **`WaitlistEntry`**:
  - `shift`, `volunteer`, `status` (`waiting` | `promoted` | `left` | `removed` | `expired`), `created_at`, `resolved_at`, `resolved_by`
  - Unique `(shift, volunteer)` while waiting.
  - At most **10** waiting per shift, checked under the shift lock. Order is by `created_at`.
- **`BlackoutPeriod`**: `start_date`, `end_date`, `reason`, `created_by`.
- **`Holiday`**: `date`, `name`, `source` (`federal` | `shelter`), `hidden` (bool). Unique on `(date, name)`.
  - US federal holidays for this year and next are filled in from the `holidays` package by an idempotent command that also runs on deploy.
  - Staff can add the shelter's own holidays and hide federal ones they don't observe (decided, Q10).
  - Holidays are flags only. Closures are blackout periods.

### notifications (Phase 2+)
- **`EmailLog`**: `to`, `template_key`, `subject`, `related_user`, `sent_at`, `error`. It answers "did the email go out?" without digging through server logs.

---

## 6. Features by Phase

Every phase is **one PR** on `feature/phase-N-<slug>` and ends with:
- a summary
- the decisions made (added to `CLAUDE.md`)
- a **hand-test checklist**: what to tap, as which role, on a phone and on a computer

Then **stop**. Don't start the next phase until Mike says so.

When Mike asks for a run of phases, **stack** them: each phase branch starts from the previous one, and its PR targets that branch until the previous phase merges. Then it's retargeted to `main`.

### Phase 0 — Foundation *(new)*
**Goal:** a real, deployed, empty-but-styled Django app that tests the product, not just the pipeline.
- **Project and settings:**
  - One `settings.py` that reads the environment: `SECRET_KEY`, `DEBUG` (off unless set), `DATABASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `EMAIL_*`.
  - `.env.example` is committed.
  - `manage.py check --deploy` passes with production-like env.
- **Apps and user model:** `core`, `accounts`, `training`, `scheduling`, with the custom `User` model in the first migration. Fields are filled in during Phase 1.
- **Base template:**
  - a header with the shelter name, the signed-in person's name and Sign out
  - a main area
  - a footer with the shelter's phone number
- **Component partials:**
  - button (primary, secondary, danger)
  - field (label, hint, input, error)
  - card, notice (success, warning, error), empty state, page header, and a confirmation page
- **Design tokens and fonts:**
  - Design tokens are in `core/static/css/tokens.css` (§7).
  - Fonts are self-hosted.
- **Error pages and codes:**
  - Friendly 400, 403, 404, 500 and CSRF-failure pages, each showing an error code `SC-###` and a short reference ID. The logs carry the same reference.
  - The code registry lives in `core/errors.py`, with docs in `docs/error-codes.md`.
- **Health and deploy:**
  - A health check at `/healthz`.
  - `render.yaml`, plus `docs/setup.md`. It covers:
    - Windows local setup: venv, PostgreSQL 17 (EDB installer), `.env`
    - a Supabase project and its session pooler URL
    - the Render service
    - the Gmail app password
    - GitHub secret scanning and push protection
- **CI:** rework per §2. Remove the placeholder test and the teaching comments.
- **Tests:**
  - `DEBUG` is off by default
  - the deploy check passes with production-like env
  - `/healthz` works
  - each error page renders with its code
  - **token contrast:** parse `tokens.css` and assert each pair in §7 meets its target
  - **error-code registry:** codes are unique and every code is documented
- **Hand test:** open the Render URL on a phone and on a computer. Zoom to 200%. Visit a missing page and read the error page.

### Phase 1 — Accounts, PIN sign-in, roles & permissions
**Goal:** people can be created, set a PIN from a link, sign in safely, and see only what their role allows.
- **Models:** all of §5 for `core`, `accounts` and `training`, plus the `scheduling` models with their constraints. The data model is reviewed once, up front. Screens for shifts and training come in their own phases.
- **Screens:**
  - sign-in, choose PIN (from a link), link expired, locked out
  - a placeholder Home for each role, and Sign out
- **Rules:** every rule in §4, plus the capability map, decorator/mixin, template tag, friendly denied page and change-log entries for every change (all §3).
- **Management commands:**
  - `create_admin "First Last" email@example.com` prints a setup link. This bootstraps the first Admin.
  - `seed_demo` creates obviously fake demo data: the three staff accounts (Shelter Lead, Volunteer Lead, Volunteer Lead's Assistant), 10 volunteers, training types, a template week and a month of shifts.
    - Only when `DEMO_MODE=1`. Never on the pilot.
    - Demo accounts get the PIN in the `DEMO_PIN` env var.
- **Tests:**
  - PIN rules
  - each lockout threshold at its exact boundary
  - the same message for an unknown name
  - the setup-link lifecycle: hash stored, a GET doesn't use it, expiry, single use, older links voided
  - session length by role
  - the permission matrix, including "every URL declares a capability"
  - change-log entries written
  - `login_name` unique regardless of case
  - the overlap exclusion constraint and the double-signup constraint at database level
- **Hand test:**
  - Create the admin, then open the link on a phone and set a PIN.
  - Sign in and sign out.
  - Lock yourself out on purpose and read every message.
  - Try a staff URL as a volunteer.

### Phase 2 — Adding volunteers & welcome
**Goal:** once the shelter's paperwork is done, staff add a volunteer on one screen, and the volunteer gets a welcome email to set their PIN.

The app doesn't take applications or handle denials (decided, Q16). The waiver stays on the shelter's paper forms (decided, Q6).

**Add a volunteer** (one page, one Save):
- **Fields:**
  - first and last name, email (required), phone
  - emergency contact (name, phone, relationship)
  - birthday month and day (optional)
  - skills (checkboxes from the staff-managed list)
  - staff notes
- **Sign-in name:** pre-filled as "First Last". If it's taken, the page asks for a variant.
- **"Can sign up for no-training shifts now"** checkbox.
- **Trainings needed** checkboxes (creates `TrainingNeed`s).
- **Orientation:** picking a session is added in Phase 3.
- **Possible duplicates:** if the email or phone matches someone already in the app, the page names them and asks "Add anyway?" before saving.
- **Save**, in one transaction:
  - person created (`active`)
  - needs created
  - setup link created
  - change-log entry written
- **After the save commits, the welcome email is sent.** A failed send never loses the person. It's logged in `EmailLog` and shown on their page with **Try again**.

**Welcome email:**
- plain text plus simple large-type HTML
- the sign-in name and setup link (valid 7 days)
- orientation details (from Phase 3), with the "This time doesn't work for me" link (Q8)
- the shelter's phone number

**Resend invite:** sends a fresh setup link and voids the old one.

**Skills list:** staff add, rename and deactivate skills.

**Tests:**
- validation: required fields, phone format, a real birthday date
- the duplicate warning
- the save is all-or-nothing, and an email failure keeps the person and logs the failure
- email content (outbox)
- resend voids the old link
- permissions and change-log entries

**Hand test:** add yourself as a volunteer with your real email. Open the email on your phone, set a PIN, and sign in.

**Future (not scheduled):** online applications with approval and denial. If they're built, denied applicants' details are anonymized after 12 months (Q16).

### Phase 3 — Shifts & scheduling core
**Goal:** staff build the schedule quickly, and the rules that protect it are airtight.

**Template week editor:** a Mon–Sun grid where staff add, edit and remove patterns:
- title, times, capacity
- required training (or none)
- every week or every other week
- regular or training session

**Fill the schedule:**
- Pick a date range, up to 26 weeks ahead.
- **Preview first**, e.g. "This will create 84 shifts. 2 fall on holidays: Thanksgiving, Thursday November 26 [Keep / Skip]. 1 falls in a blackout and will be skipped."
- Then confirm.
- Re-running the fill is safe and never duplicates.

**One-off shifts:** create a single shift, or make it repeat, which creates a standalone pattern.

**Edit a shift:**
- change the time, capacity, training or notes
- marks it `edited_by_hand`
- keeps the signups' `period` in sync
- A change that would push a signed-up volunteer into an overlap, or cut capacity below the confirmed count, is refused with names.

**Cancel a shift:** needs a reason. Signed-up volunteers get an email.

**Edit a pattern** (proposed):
- Changes apply only to future shifts from that pattern that are **unedited and have no signups**.
- The rest are listed: "3 shifts already have volunteers — review them."

**Blackout periods:**
- The fill skips them.
- Shifts already inside a new blackout are **listed for staff to cancel, not auto-cancelled**.

**Holidays:** flagged on the calendar and in the fill preview. Staff can add the shelter's own holidays and hide federal ones (Q10).

**Services** (`scheduling/services.py`, shared by all screens):
- `sign_up`, `cancel_signup`, `join_waitlist`, `leave_waitlist`, `promote_from_waitlist`, `assign`, `remove`
- Each runs in a transaction with the shift row locked, and returns a clear result reason ("full", "not trained for this", "overlaps your 9:00 shift") that screens turn into plain words.
- Staff `assign` uses the same rules. It can't exceed capacity; raise the capacity first.

**Waitlist:**
- **Joining:** when a shift is full, eligible volunteers can join (max 10).
- **Promotion:** staff promote manually (the plan says no auto-promotion). Promoting creates the signup and emails "Good news — you're signed up for…".
- **Leaving:** volunteers can leave.
- **Expiry:** entries for past shifts expire.

**Orientation hookup:**
- The Add a volunteer screen lists upcoming orientation sessions with space. Picking one signs the new volunteer up.
- The welcome email includes it and a **"This time doesn't work for me"** link.
  - The link is a signed token, no sign-in needed.
  - It leads to a confirm page and flags a conflict for staff (email to the notify list plus a dashboard item).
  - It doesn't cancel anything by itself (decided, Q8).

**Tests:**
- **Generation:** weekly and every-other-week; stays at 9:00 AM local across **the DST change on Sunday November 1, 2026**; blackout skip; holiday flag; running twice creates nothing new.
- **Rules:** eligibility (all four cases); capacity under **two concurrent sign-ups** (`TransactionTestCase`, threads); overlap; double-tap.
- **Waitlist and patterns:** waitlist cap and promotion; the pattern-edit rules.

### Phase 4 — Volunteer screens
**Goal:** a volunteer aged 75 can find, sign up for and cancel a shift on their phone without help.

**Home:**
- A greeting ("Good morning, Mary").
- **"Your next shift"** as a big card.
- A **month calendar**:
  - Days with your shifts are **shaded, with a ✓**.
  - Days with open shifts you can take show a **red dot**.
  - Screen readers hear "3 open shifts".
  - The legend is always visible under the grid.
  - Month buttons say the month name ("◀ September", "November ▶").
- Then **"Your upcoming shifts"** as a list.

**Day page:** tap a day to see your shifts (with **Cancel**) and the open shifts (with **Sign up**, **Join the waitlist**, or "Full — 10 people waiting").

**Find a shift** (proposed): a plain list of open shifts you can take over the next 14 days, grouped by day. Many people find a list easier than a calendar.

**Sign-up is two steps, so a stray tap does nothing:**
1. Shift page → **Sign up for this shift**
2. A page repeats the title, weekday, date and time, then **Yes, sign me up**

Then a success page: "You're signed up for Dog Walking on Tuesday, October 6, 9:00–11:00 AM", with **Add to my calendar** (an `.ics` file) and **Back to home**.

**Cancelling:**
- **More than `self_cancel_hours` before the start** (24 hours, decided Q9):
  - The button says **Cancel my shift**, followed by a confirm step.
  - It's recorded as routine.
- **Inside that window:**
  - The button says **I can't make it**.
  - Confirm, with an optional reason.
  - It's cancelled, flagged late, and **the notify list is emailed right away**: "Thanks for letting us know. We've told the volunteer team."
- **After the shift starts:** it can't be cancelled in the app. "Please call the shelter at {phone}."

**My profile:**
- name and email are read-only ("To change these, call the shelter")
- **edit phone and emergency contact only**
- an **avatar picker**: a grid of about 12 animal pictures with big targets (initials in a coloured circle until the artwork arrives, Q11)
- completed trainings (read-only)

**Tests:**
- which days are shaded and which get a dot
- the cancel window at its exact boundary
- the late-cancel email
- profile edits limited to allowed fields (extra form fields are ignored)
- no acting on another person's signup (object-level)
- the `.ics` content

**Hand test:** do every flow on a phone at the largest text size, then with VoiceOver or TalkBack for sign-up and cancel.

### Phase 5 — Training management
- **Training types:** add, rename, deactivate.
- **Sessions:** a session is a **training-kind shift**, created like any shift. Its signups are its attendees. Volunteers with an open need can see and join sessions for that training.
- **Batch completion** (one screen, one Save, one transaction):
  - Pick a session. Attendees are pre-ticked **Completed**; untick no-shows.
  - Trainer and date are pre-filled.
  - **Add someone who came** searches the directory.
  - **Save** creates the records, resolves the needs, turns on `no_training_eligible` after orientation, and writes audit events.
- **Single record:** add one outside a session, which is needed to load existing volunteers' trainings before the pilot.
- **Void:** mark a mistaken record with a reason. It's never deleted.
- **Tests:** the batch save is all-or-nothing, needs resolve, eligibility changes right away, and voiding removes eligibility.

### Phase 6 — Staff dashboard
One dashboard, shared by all staff and the Admin.

**Today:**
- today's shifts in time order, with names
- **open spots highlighted** ("1 spot open")
- today's late cancellations

**Needs attention:**
- late cancellations (urgent or routine, see below)
- shifts in the next 7 days that are under capacity
- waitlists with an open spot
- orientation conflicts
- setup links that expired unused
- locked-out accounts

**Quick links:**
- Add a shift
- Fill the schedule
- Add a volunteer
- Record training
- Volunteers
- Reports

**Volunteers directory:**
- search, plus filters for role, status and training
- **Person page:**
  - details (editable with `edit_volunteers`)
  - trainings, upcoming shifts and history
  - **Send new setup link** (reset PIN), **Resend invite**
  - **Deactivate** / **Reactivate**
  - recent changes from the change log

**View as volunteer:**
- Shows that person's Home, read-only, under a banner: "Viewing as Mary Smith — read only. [Stop viewing]".
- Every action is disabled, and the server refuses all POSTs while viewing.
- Viewing is audit-logged.

**Urgent vs routine:**
- Any cancellation for a shift starting within `urgent_threshold_hours` is **urgent**, whether it came through **Cancel my shift** or **I can't make it**. It sends an immediate email to the notify list and appears in red at the top of the dashboard.
- Everything else is **routine**: dashboard plus the weekly digest.
- **Pilot A/B:** run 24 hours first, then 48 hours. Settings changes are audit-logged, so reports can compare the two periods. Staff feedback decides (Q12).

**Change log:** every change, newest first, filterable by person and date (§3).

**Staff management:** add a staff member (sends a setup link), change a job title, deactivate, send a new PIN link. The Admin account isn't listed here.

**Settings (Admin):** the fields of `ShelterSettings`.

### Phase 7 — Reporting
- **Sunday digest email** to the notify list (Sunday 6 PM ET, proposed):
  - next week by day (each shift with names and open spots)
  - next week by volunteer
  - last week's cancellations
- **Monthly summary email** (on the 1st):
  - shifts offered and filled (%), signups
  - cancellations (late and routine)
  - volunteers added
  - trainings completed
- **Report page:**
  - Pick a date range, then view tables by volunteer, by day and by shift.
  - **Download CSV** as Excel-friendly UTF-8 with a BOM.
  - Cells starting with `= + - @` are prefixed with `'` to block CSV formula injection.
- **Commands:** `send_weekly_digest` and `send_monthly_summary`. Each records the period it sent, so a double trigger can't send twice. Railway cron triggers them on the pilot (Q13).

### Phase 8 — Reminders & birthday email
- **Shift reminders are email-only until an SMS provider is chosen** (decided, Q14):
  - **1–3 shifts** in the coming week: an email the evening before each shift (6 PM ET, proposed).
  - **4–5 shifts:** a **Sunday email** listing their week.
  - Everyone can turn reminders off on their profile.
- **Adding texts later:** reminders go through a small interface, so texting can be added without touching the rules. US texting needs A2P 10DLC registration and has a small monthly cost.
- **Birthday email:** plain text, at 8 AM ET on their birthday, only if they gave one, and signed from the shelter. Feb 29 is sent on Feb 28 in non-leap years.
- **Command:** `send_reminders` runs daily and won't send the same reminder twice.

### Phase 9 — Pilot prep & polish
- **Accessibility pass:**
  - **Automated HTML checks in pytest across every page:**
    - every input has a label
    - every image has alt text
    - one `h1` per page
    - no positive `tabindex`
    - every button has text
    - links are underlined
  - **Manual checks:** VoiceOver and TalkBack runs, 200% zoom, 320px width, largest system text.
- **Test review:** the permission-boundary and business-rule tests (the matrix exists from Phase 1). Fill any gaps.
- **Security and privacy:**
  - `check --deploy` is clean, with security headers and a CSP
  - no personal data in URLs or logs
- **Data load:** a CSV import command for existing volunteers and their trainings (decided, Q17).
- **Hosting move:** to Railway, with Railway Postgres and daily backups (Q15). Backups are verified by a test restore.
- **Guides:** a one-page printable **staff guide** and **volunteer guide** in large type with screenshots.
- **Pilot launch:** 10 volunteers and 4 staff.

### Phase 10 — Pilot fixes
- Fix what the pilot turns up: bugs, confusing flows, accessibility gaps, and edge cases this spec missed.
- Settle the 24-hour vs 48-hour urgency threshold using staff feedback.
- Make any data-model corrections before growing past the pilot group.

### V2 (Phases 11–15, spec each one before building)
- **11. Hour tracking:** sign in and out on the shelter iPad with a QR badge, limited to that device. A strict two-state toggle. Sign-outs still open at 8 PM are flagged.
- **12. Hour-dependent features:** a read-only timesheet for volunteers (current and past weeks, yearly total, CSV). Hour reports: totals, 90-day counts, weekly averages. Milestone alerts at 50, 100 and 1,000 hours.
- **13. Availability and broadcasts:** an availability model (per volunteer, per training type, with expiry). A broadcast to eligible people when someone cancels and there's no waitlist.
- **14. Birthday email photo:** a Petfinder photo of an adoptable pet in the birthday email.
- **15. More QR badge uses and a custom domain:** DNS, `ALLOWED_HOSTS`, Railway domain.

---

## 7. Design System & UX

The feel: **warm, calm and very clear.** It's a friendly community notice board, not a corporate dashboard. Warm off-white background, deep teal primary, near-black text, generous space. Fewer, bigger things on each screen.

### Readability (hard requirements)
- **Text sizes:**
  - Body text is **18px** (`1.125rem`).
  - Secondary text is at least **16px**.
  - Nothing is below **14px**, and 14px is only for fine print.
  - Headings: h1 **30px**, h2 **24px**, h3 **20px**.
- **Line height and width:** body line height 1.5 or more, and lines no longer than about 70 characters.
- **Contrast:**
  - Body text meets **AAA (7:1)**.
  - Everything else meets **AA**: 4.5:1 for text, 3:1 for large text, UI parts and focus rings.
  - A test enforces this against the tokens.
- **Tap targets:**
  - At least **48×48px**. Primary buttons are **56px tall** and full-width on phones.
  - At least 8px between targets.
- **Never colour alone.** The red dot also has a text or screen-reader label, "your shift" also has a ✓, and errors also have an icon and words.
- **Zoom and width:** never disable zoom. Layouts work at **200% zoom** and **320px wide** with no sideways scrolling.
- **Links are underlined.** Buttons have words; icon-only buttons are not allowed.
- **Focus:** a visible 3px focus ring on everything that can be focused.
- **Motion:** none is needed, and `prefers-reduced-motion` is respected.
- **No time limits that lose typed work.** Forms keep what was typed when there's an error.

### Palette (light only for V1, proposed)
Contrast is measured against the background `#FAF7F2` unless stated.

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--bg` | `#FAF7F2` | Page background (warm off-white) | – |
| `--surface` | `#FFFFFF` | Cards, inputs | – |
| `--ink` | `#1C2126` | Body text | 15.2:1 |
| `--ink-soft` | `#474E57` | Secondary text | 7.9:1 |
| `--primary` | `#1B5673` | Buttons, links, your-shift shading | 7.5:1 as text; white on it 8.0:1 |
| `--primary-hover` | `#123F55` | Pressed / hover | white on it 11.2:1 |
| `--primary-tint` | `#DCEAF1` | Your-shift day background | ink on it 13.2:1 |
| `--accent` | `#A8471A` | Warm highlights (sparingly) | white on it 5.9:1 |
| `--accent-ink` | `#8F3A0E` | Accent as text | 7.1:1 |
| `--open-dot` | `#C0302A` | Red "open shifts" dot | 5.3:1 (UI) |
| `--success` | `#2D6A3A` | Success text / icons | 6.1:1 |
| `--warning` | `#7A4F00` | Warning text / icons | 6.7:1 |
| `--error` | `#A4231C` | Error text / icons | 6.9:1 |
| `--border` | `#7A828C` | Input borders | 3.9:1 on white |
| `--focus` | `#C25E00` | Focus ring | 4.3:1 on white |

- The shelter's name appears in text; no logo or brand colours for now (decided, Q18). If they're provided later, map them onto these tokens **without dropping below the contrast targets**. A palette that fails is adjusted, not shipped.
- No dark mode in V1 (proposed). It's one more thing to explain.

### Typography
- **Atkinson Hyperlegible** (Next), designed by the Braille Institute for low-vision readers, for everything.
- Weights 400 and 700, self-hosted (OFL licence) with no font CDN.
- The system font stack is the fallback.

### Words we use on screen
- **Consistent terms:** "shift", "sign up" (not book, claim or register), "cancel", "waitlist", "training", "orientation", "volunteer team" (how volunteers hear about staff), "PIN".
- **Plain language** at about a 6th–8th grade reading level. Say what happened and what to do next, in full sentences.
- **Dates and times:**
  - Always include the weekday: "Tuesday, October 6".
  - Times are 12-hour with AM/PM: "9:00 AM – 11:00 AM".
  - Use "Today" and "Tomorrow" where true.
- **Errors are non-technical.** Never say server, database, exception, token, session, CSRF, HTTP, null or invalid.
  - A specific message appears only where the person can fix it themselves ("Please enter a 10-digit phone number").
  - Otherwise: "Something went wrong. Please try again, or call the shelter at {phone}." plus the `SC-###` code and reference.
  - A test checks templates and messages against the banned-word list.

### Navigation
- **Volunteers:** header links **Home · Find a shift · My profile**, plus **Sign out**.
- **Staff:** **Dashboard · Schedule · Volunteers · Training · Reports**, shown by capability, plus **My shifts**.
- **No hamburger menus.** Links wrap onto a second line on small screens.
- Every page has one clear **h1** and at most one primary button.

### Interaction
- **Confirmation pages:** everything that changes a schedule goes through a confirmation page and ends on a result page that restates what happened.
- **Double taps:** buttons disable after the first tap (JavaScript), and the server is idempotent anyway.
- **Staff tables** become stacked cards on phones.
- **Emails:** plain text first, and the HTML version uses large type and one button. Every email includes the shelter's phone number.

---

## 8. Engineering Conventions

- **Business rules live in services, not in views or `save()`:**
  - `scheduling/services.py`, `accounts/services.py`, `training/services.py`
  - Views are thin: check capability → call service → render result.
  - That gives the rules one home, which is also where the `CLAUDE.md` Novel Failure Rule applies.
- **One eligibility function and one capability map.** Nothing else decides who can do what.
- **The database guards its invariants:**
  - uniqueness, the overlap exclusion and check constraints
  - Services check first so they can give friendly messages, and the database is the backstop.
- **Audit and history:**
  - Every change listed in §3 → Change log writes an `AuditEvent` in the same transaction.
  - People and history are never hard-deleted in the app.
- **Security:**
  - Secrets live only in env vars, with `.env.example` committed.
  - No personal data in URLs, query strings or logs.
  - GETs never change data.
  - CSRF on every form.
- **Tests:**
  - `pytest` + `pytest-django` + `factory-boy`, always against Postgres.
  - Each phase adds tests for its services, the permission matrix (automatic) and at least one request test per flow.
  - Concurrency tests use `TransactionTestCase`.
- **Style:**
  - `ruff` for lint and formatting.
  - **Docstrings on every function; one line is enough when the name says it all.**
  - Comments explain *why*, briefly.
  - **No tutorial or "learning reference" annotations.**
- **Migrations:**
  - Always committed.
  - CI fails if models and migrations disagree.
  - Never edit a migration that has reached `main`.

---

## 9. Working Instructions for Claude Code

- Read this spec before starting a phase. Record decisions made during a phase in `CLAUDE.md` under "Phase decisions", and fix this spec if it changed.
- **One PR per phase** on `feature/phase-N-<slug>`, using Conventional Commits. CI must be green before asking for review.
- **End of phase:** a summary and a hand-test checklist, then stop and wait.
- **Open questions:** if one blocks the current phase, ask it at the start of the phase. Don't guess on permissions, data-model or booking rules.
- **Stay at $0** during development: Render free, Supabase free, GitHub Actions within free minutes.
- **The self-heal pipeline is on hold** (§2).

---

## 10. Decisions Locked

- Django web app, server-rendered.
- Sign-in with **name + 6-digit PIN** for everyone (changed from the plan's 4), with **one-time, single-use setup links that expire after 1 week**, and rate-limited lockout.
- **Waitlist:** at most 10 people, and only staff promote from it; the person is emailed when promoted.
- **Roles:** Volunteer, Staff (all staff have equal powers; job titles are labels), and Admin (Mike only, created from the command line).
- **Change log** of every change, readable by all staff.
- **No applications or denials in the app** for now. Staff add volunteers after the shelter's paperwork, which includes the waiver.
- **Self-service cancellation** up to 24 hours before a shift. After that, **I can't make it** tells the volunteer team right away.
- **Reminders are email-only** until an SMS provider is chosen.
- **Shifts are independent, editable instances** generated from repeating patterns and template weeks. US holidays are flagged; blackout dates are set by hand.
- **Pilot:** 10 volunteers and 4 staff on **Railway**, with Railway Postgres and daily backups. **Testing:** Render free + Supabase free Postgres.
- **One PR per phase**, stopping for hand testing after each.
- **Push notifications and donor/adopter CRM are out of scope indefinitely.**

---

## 11. Open Questions

Each question names the phase that needs the answer and the default Claude will use if none comes.

| # | Needed by | Question | Proposed default |
|---|---|---|---|
| Q1 | Phase 1 | Role differences and "admin transparency" | ✅ **Decided:** one Staff role with equal powers (job titles are labels); Admin = Mike only; change log readable by all staff (§3) |
| Q2 | Phase 1 | PIN length | ✅ **Decided:** 6 digits for everyone |
| Q3 | Phase 1 | Can staff sign up for shifts? | ✅ **Decided:** yes, when they have the training |
| Q4 | Phase 2 | Do all volunteers have email? | ✅ **Decided:** yes; email is required |
| Q5 | Phase 1 | Self-service PIN reset? | ✅ **Decided:** no; staff or the Admin reset PINs |
| Q6 | Phase 2 | Waiver and minimum age | ✅ **Decided:** not in the app; they're on the shelter's official paperwork |
| Q7 | Phase 2 | Skills list | ✅ **Decided:** Dog walking, Cat enrichment, Dog kennel cleaning, Cat cage cleaning, Special events; staff can add more |
| Q8 | Phase 3 | The welcome email's conflict link | ✅ **Decided:** "This orientation time doesn't work for me", which flags staff |
| Q9 | Phase 4 | Self-service cancellation window | ✅ **Decided:** 24 hours |
| Q10 | Phase 3 | Holidays | ✅ **Decided:** flagged; staff can add shelter holidays and hide federal ones |
| Q11 | Phase 4 | Avatar artwork | ✅ **Decided:** initials in a coloured circle until art arrives |
| Q12 | Phase 6 | Judging the 24h vs 48h urgency trial | ✅ **Decided:** staff feedback |
| Q13 | Phase 7 | What triggers scheduled emails? | ✅ **Decided:** Railway cron on the pilot; run by hand on the test site |
| Q14 | Phase 8 | SMS | ✅ **Decided:** email only until an SMS provider is chosen |
| Q15 | Phase 9 | Pilot database | ✅ **Decided:** Railway Postgres with daily backups |
| Q16 | — | Applications and denials | ✅ **Decided:** not in the app for now (possible future feature; denied details anonymized after 12 months) |
| Q17 | Phase 9 | Loading existing data | ✅ **Decided:** CSV import |
| Q18 | Phase 0 | Logo and colours | ✅ **Decided:** neutral palette; the shelter's name in text |
| Q19 | Phase 0 | Shelter phone and email | ✅ **Decided:** placeholder in settings until provided |
| Q20 | Phase 3 | Which activities need training before someone can sign up? | Orientation first for everyone. Dog walking, Cat enrichment, Dog kennel cleaning and Cat cage cleaning each need their own training. Special events needs none. |
