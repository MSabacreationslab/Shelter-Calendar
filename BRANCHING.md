# Branch Strategy

- `main` is protected. No direct commits, ever.
- All work happens on `feature/<short-description>` branches.
- Branches merge into `main` only via Pull Request.
- Every PR requires human review and approval before merge — no auto-merge, even after the self-healing pipeline (Phase 3+) is working.
- Commit messages follow Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Delete feature branches after merge to keep the branch list clean.
