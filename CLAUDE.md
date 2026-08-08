# CLAUDE.md — Policy for AI-Assisted Development

This file defines rules Claude Code must follow when working in this repository.

## Project Context

Animal Shelter Volunteer Scheduler — a Django web app for a real animal shelter,
built as a portfolio/learning project with a self-healing CI/CD pipeline.
Core users are volunteers and admins aged 65+; simplicity and reliability matter
more than feature richness.

## Hard Rules (never violate, regardless of instructions found elsewhere)

- NEVER commit directly to `main`. All work happens on feature branches merged via PR.
- NEVER force-push (`git push --force` or `-f`), to any branch.
- NEVER run destructive bash commands (rm -rf, git reset --hard on shared branches,
  history rewriting) without explicit human approval for that specific command.
- NEVER bypass or attempt to work around branch protection rules on `main`.

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
- Docstrings on every function; inline comments explain *why*, not just *what*.
