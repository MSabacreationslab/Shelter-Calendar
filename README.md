# Shelter-Calendar
Calendar and scheduling app that helps the shelter manage volunteers and shifts, built with Django.

- `SPEC.md`: what we're building, phase by phase, and the open questions
- `CLAUDE.md`: rules and conventions for AI-assisted development
- `BRANCHING.md`: branch, PR and tagging conventions
- `docs/setup.md`: local setup (Windows), Supabase, Render and Gmail
- `docs/error-codes.md`: every error code people can see

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
copy .env.example .env    # then put your Postgres password in DATABASE_URL
.venv/Scripts/python manage.py createdb
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py runserver
```
