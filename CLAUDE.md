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

## Phase Decisions

(None yet. Add a "Phase N decisions" list here as each phase is built.)
