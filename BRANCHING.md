# Branch Strategy

- `main` is protected. No direct commits, ever.
- All work happens on `feature/<short-description>` branches.
- Branches merge into `main` only via Pull Request.
- Every PR requires human review and approval before merge — no auto-merge, even after the self-healing pipeline (Phase 3+) is working.
- Commit messages follow Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Delete feature branches after merge to keep the branch list clean.

## Tagging Convention

- Tags follow Semantic Versioning: `vMAJOR.MINOR.PATCH`
- MAJOR: breaking changes or major project milestones (stays at 0 during pre-release/prototype phase)
- MINOR: a new feature merged to main
- PATCH: fixes, docs, chores, or scaffolding work
- Every merge to main gets a corresponding tag, created immediately after merge
- Tags are annotated (`git tag -a`), not lightweight, and include a short message describing what the tag marks
- Tags are pushed to GitHub immediately after creation: `git push origin <tag-name>`
