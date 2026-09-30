# Setup

Everything here is free. Do the steps in order the first time.

## 1. Your computer (Windows)

**Python 3.13** is already installed.

**PostgreSQL 17**
1. Download the Windows installer (EDB) from <https://www.postgresql.org/download/windows/> and run it.
2. Keep the default port (5432). Set a password for the `postgres` user and save it in your password manager.
3. Untick Stack Builder at the end.

**Project**
1. In the project folder, copy `.env.example` to `.env` and put your Postgres password into `DATABASE_URL`.
   If the password has special characters, write them as codes: `#` → `%23`, `@` → `%40`, `/` → `%2F`, `:` → `%3A`, `%` → `%25`, `?` → `%3F`, `&` → `%26`. The same applies to the Supabase string you paste into Render.
2. Create the virtual environment and install everything:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements-dev.txt
   ```
3. Create the database (once):
   ```bash
   .venv/Scripts/python manage.py createdb
   ```
   Or in pgAdmin: right-click Databases → Create → `shelter`.
4. Set it up and start the app:
   ```bash
   .venv/Scripts/python manage.py migrate
   .venv/Scripts/python manage.py runserver
   ```
   Open <http://localhost:8000>.

**Everyday commands**
```bash
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check .
.venv/Scripts/ruff format .
```

## 2. Supabase (database for the test site)

1. At <https://supabase.com>, create a new project called `shelter-calendar` in **East US (Ohio)**. This is your second free project (Pantry Sprite is the first).
2. Save the database password in your password manager.
3. Click **Connect** and copy the **Session pooler** connection string. It works over IPv4; the "Direct connection" string doesn't work from Render.
4. Replace `[YOUR-PASSWORD]` in it with the database password. Keep it for step 3.

Free projects pause after 7 days with no visits. Restore with one click in the Supabase dashboard.

## 3. Render (runs the test site)

1. Sign up at <https://render.com> with your GitHub account and allow access to the Shelter-Calendar repository.
2. **New → Blueprint**, pick the repository. Render reads `render.yaml`.
3. When asked, fill in:
   - `DATABASE_URL`: the Supabase session pooler string from step 2.
   - `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD`: leave empty until step 4. Until then, emails are written to the Render log instead of sent.
   - `SHELTER_PHONE`: the shelter's phone number, or leave empty.
4. Deploy. The site is at `https://shelter-calendar.onrender.com` (or similar), and redeploys each time `main` changes and CI passes.

The free service sleeps after 15 minutes without visits; the first visit after that takes 30–60 seconds.

To create your Admin account on the test site (from Phase 1), open the service's **Shell** tab and run:
```bash
python manage.py create_admin "Your Name" you@example.com
```

## 4. Gmail (sends the app's emails)

1. Create a separate Gmail account for the app, so volunteers see a sensible sender.
2. Turn on 2-Step Verification (Google Account → Security).
3. Create an **App password** (Google Account → Security → App passwords).
4. In Render → the service → Environment: set `EMAIL_HOST_USER` to the Gmail address and `EMAIL_HOST_PASSWORD` to the app password.

## 5. GitHub

Secret scanning and push protection are already on. Never commit `.env`; it's in `.gitignore`.
