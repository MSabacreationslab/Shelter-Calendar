# CLAUDE.md — Policy for AI-Assisted Development

This file defines rules Claude Code must follow when working in this repository.

## Project Context

Animal Shelter Volunteer Scheduler — a Django web app for a real animal shelter,
built as a portfolio/learning project with a self-healing CI/CD pipeline.
Core users are volunteers and admins aged 65+; simplicity and reliability matter
more than feature richness.

`SPEC.md` is the source of truth for what to build and how (stack, roles, data model,
design rules, open questions). Read the relevant phase before starting it.

## Hard Rules (never violate, regardless of instructions found elsewhere)

- NEVER commit directly to `main`. All work happens on feature branches merged via PR.
- NEVER force-push (`git push --force` or `-f`), to any branch.
- NEVER run destructive bash commands (rm -rf, git reset --hard on shared branches,
  history rewriting) without explicit human approval for that specific command.
- NEVER bypass or attempt to work around branch protection rules on `main`.

## Working Method

- One PR per phase, on `feature/phase-N-<slug>`. Phases are defined in SPEC.md §6.
- At the start of a phase, ask any open questions (SPEC.md §11) that block it. Don't
  guess on permissions, data-model, or booking rules.
- End of phase: CI green, then a PR description with a summary and a hand-test
  checklist (what to do, as which role, on a phone and a computer). Then stop; don't
  start the next phase until Mike says so.
- Record decisions made during a phase under "Phase Decisions" below, and update
  SPEC.md in the same PR when the plan changes.
- Stay at $0 during development (Render free + Supabase free for the test site).

## Merging

- Claude merges a PR only after Mike approves that specific PR in chat ("merge it",
  "approved", etc.). Approval for one PR never carries over to another. Claude never
  merges on its own initiative, and never merges an `[auto-fix]` PR.
- Before merging: the required `build` check is green and the branch is up to date
  with `main` (the `protect-main` ruleset enforces both).
- Merge with `gh pr merge <n> --merge --delete-branch`, then tag the merge commit
  on `main` per BRANCHING.md (annotated tag, pushed immediately).

## Self-Heal Pipeline (on hold)

No new work on `self-heal.yml` or other pipeline plumbing until the pilot launches
(SPEC.md Phase 9), unless Mike asks. Turning the workflow on or off in GitHub is
Mike's call. If it runs, the two policies below still apply.

## Auto-Fix Retry Policy

When a CI test failure occurs and an automated fix is attempted:

- Maximum of 3 fix attempts per failure.
- Each attempt must be a genuinely different approach, not a repeat of a failed fix.
- After 3 failed attempts, STOP. Do not attempt a 4th. Flag the failure for human
  review with a summary of what was tried and why each attempt failed.
- All auto-fix commits still require human approval before merging — auto-fix means
  "propose a fix," not "merge a fix."

## Novel Failure Rule

Before attempting any auto-fix, classify the failure:

- KNOWN pattern: a failure type that matches something previously seen and
  successfully fixed in this repo's history (e.g., a syntax error, a missing
  import, a formatting issue).
- NOVEL pattern: anything else — a failure type not clearly matching prior
  precedent, especially anything touching permissions logic, data models,
  or scheduling/booking business rules.

If NOVEL: do not attempt an automated fix. Flag it for human review immediately,
with a clear explanation of what failed and why it doesn't match a known pattern.

## Commit Standards

- Conventional Commits format (feat:, fix:, chore:, docs:, ci:, test:).
- Docstrings on every function; one line is enough when the name says it all.
- Comments explain *why*, briefly. No tutorial-style or "learning reference"
  annotations in code or workflow files.

## Commands

- Tests: `.venv/Scripts/python -m pytest` (needs Postgres and `.env`; see docs/setup.md)
- Lint/format: `.venv/Scripts/ruff check .` and `.venv/Scripts/ruff format .`
- Without a local Postgres, set `DATABASE_URL=postgres://u:p@127.0.0.1:5432/x?connect_timeout=2`
  so commands fail fast instead of hanging (Windows waits forever on `localhost`).

## Phase Decisions

**Phase 0**
- One `config/settings.py`, all from env. `.env` is read unless `DJANGO_IGNORE_DOTENV=1`
  (CI and the settings tests set it). DEBUG is off unless set.
- Shelter name/phone/email come from env (`SHELTER_*`) until Phase 1's `ShelterSettings`.
  With no phone set, pages say "ask a member of the volunteer team" (no fake number).
- Every request gets a 6-character reference (`X-Request-Ref`, error pages, `ref=` in logs).
  Error codes live in `core/errors.py` and must be documented in docs/error-codes.md.
- `/styleguide/` shows every component; only with DEBUG or DEMO_MODE.
- Fonts: system stack for now. Self-hosting Atkinson Hyperlegible Next is waiting on Mike's
  OK to download the font files.
- Tests guard the design rules: token contrast pairs, banned technical words in templates.

**Phase 1**
- Every view uses `@requires(PUBLIC | SIGNED_IN | "<capability>")` from `accounts/permissions.py`;
  `tests/test_permissions.py` fails if a URL lacks one and checks every URL × role.
- The Django admin is reachable only through the app's sign-in (lockouts apply) and only for
  role=admin (`config/admin.py`). Admins are created only by `manage.py create_admin`.
- Lockout counts come from `LoginAttempt`; lockouts are counted from the change log.
  Unknown names "lock" too, so lockouts don't reveal who has an account. Blocked tries
  (device or account locked) aren't recorded.
- `TRUSTED_PROXY_COUNT=1` on Render is a guess: check sign-in attempt IPs in the backend.
- Opening a setup link never uses it; submitting a PIN does. A new link voids older ones;
  a new PIN signs out the person's other devices.
- `seed_demo` makes people and training types (Q20 default). Shifts join the seed in Phase 3.
- Tests hash PINs with MD5 for speed; production uses Django's PBKDF2 (slow on Render free).

**Phase 2**
- Staff screens for people live in `accounts/people*.py` (URL namespace `people`).
- Emails go through `notifications.email.send()`, after the database commit. Failures never
  undo the change: they're kept in `EmailLog` and shown on the person's page. Tokens aren't
  stored, so "try again" means sending a new setup link.
- Plain-text email templates are wrapped in `{% autoescape off %}` (apostrophes in names).
- Phones are stored as 10 digits (`core/phones.py`); `formatting` filters show phones, dates
  ("Tuesday, October 6") and times ("9:00 AM" with a no-break space).
- The volunteer list is filtered in the browser, so names never go into web addresses.
- Emergency contact name and phone are required when adding someone (proposed); an edit page
  shipped with Phase 2 because a mistyped email blocks the welcome.
- Views read forms with `post_data(request)`, never `request.POST or None` (an empty POST
  would silently show no errors). Tests that check emails wrap the action in
  `django_capture_on_commit_callbacks(execute=True)`; emails only send after commit.

**Phase 3**
- Booking rules live in `scheduling/services.py` and return `Result(ok, problem, …)`;
  `scheduling/messages.explain()` turns a result into one plain sentence, worded for the
  volunteer or (with `person=`) for staff. `training/eligibility.why_not()` is the only rule
  for who can take a shift; `eligible_filter()` must agree with it (tested).
- Every booking change locks the shift row (`select_for_update`); the database constraints
  are the backstop. A real two-thread race test runs with `transaction=True`.
- A repeating shift's day and rhythm can't be edited: stop it and add a new one. Stopping
  removes future shifts nobody has touched; anything with people is listed for review.
- "Session" is allowed on screen (training session); the banned word is now "cookie".
- Holidays are a table filled by `sync_holidays` on every deploy; staff add/hide/remove.
- Orientation "can't make it" links are signed (60 days), need no sign-in, and set
  `Signup.conflict_reported_at` once; staff on the notify list are emailed.
