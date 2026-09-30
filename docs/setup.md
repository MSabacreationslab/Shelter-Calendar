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
4. Replace `[YOUR-PASSWORD]` in it with the database password, **brackets included**. Keep it for step 3.

A password with only letters and numbers avoids trouble: other characters have to be written as codes in the address (`#` → `%23`, `@` → `%40`, `/` → `%2F`, `:` → `%3A`, `%` → `%25`, `?` → `%3F`, `&` → `%26`). To change it: Project Settings → Database → Reset database password.

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

### Running commands against the test site

Render's free plan has no Shell, so commands like `create_admin` and `seed_demo` run on your computer, pointed at the Supabase database. In **PowerShell**, in the project folder:

```powershell
$env:DATABASE_URL = "the same value as DATABASE_URL in Render"
$env:DATABASE_SSL_REQUIRE = "1"
$env:SITE_URL = "https://shelter-calendar.onrender.com"
$env:DEBUG = "1"
```

Then, in the same window:

- Create your Admin account (from Phase 1). It prints a link to open on your phone:
  ```powershell
  .venv\Scripts\python manage.py create_admin "Your Name" you@example.com
  ```
- Add demo people, training and shifts (from Phase 1; shifts from Phase 3). `DEMO_PIN` is the PIN every demo account gets:
  ```powershell
  $env:DEMO_MODE = "1"; $env:DEMO_PIN = "a 6-digit PIN"
  .venv\Scripts\python manage.py seed_demo
  ```

- Send the report emails by hand (the pilot will run these on a schedule). They go to the notification emails in Settings, and each period is only sent once unless you add `--again`:
  ```powershell
  .venv\Scripts\python manage.py send_weekly_digest
  .venv\Scripts\python manage.py send_monthly_summary
  ```
  Add `--date 2026-10-04` to act as if it's another day (the digest covers the week after that date; the summary covers the month before it).

Close the window when you're done, so the settings don't linger. `DEBUG` here only affects the command on your computer, not the site.

## 4. Gmail (sends the app's emails)

1. Create a separate Gmail account for the app, so volunteers see a sensible sender.
2. Turn on 2-Step Verification (Google Account → Security).
3. Create an **App password** (Google Account → Security → App passwords).
4. In Render → the service → Environment: set `EMAIL_HOST_USER` to the Gmail address and `EMAIL_HOST_PASSWORD` to the app password.

## 5. GitHub

Secret scanning and push protection are already on. Never commit `.env`; it's in `.gitignore`.
