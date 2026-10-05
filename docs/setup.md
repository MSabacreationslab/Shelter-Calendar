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
- Add demo people, training and four weeks of staffed shifts. `DEMO_PIN` is the PIN every demo account gets. It sends no emails, and running it again tops the schedule up to four weeks ahead:
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
- Send shift reminders and birthday emails by hand (the pilot runs reminders every evening at 6 PM and birthdays every morning at 8 AM). Each reminder is only ever sent once:
  ```powershell
  .venv\Scripts\python manage.py send_reminders
  .venv\Scripts\python manage.py send_birthday_emails
  ```
  `send_reminders` emails everyone about tomorrow's shifts; on a Sunday it first sends next week's list to anyone with 4 or more shifts. Both take `--date` too.
- Load the shelter's volunteer spreadsheet (from Phase 9). In Excel choose **File → Save As → CSV UTF-8**, and save it **outside the project folder** (it has people's details; git ignores spreadsheets anyway). First a preview, which changes nothing:
  ```powershell
  .venv\Scripts\python manage.py import_volunteers "C:\Users\you\Documents\volunteers.csv"
  ```
  It lists how many people it would add, who needs approval, the minors, the jobs it found, and every row it would skip or that's worth a look (with row numbers). Fix anything in the spreadsheet, save as CSV again, and repeat. When it looks right, add `--save`:
  ```powershell
  .venv\Scripts\python manage.py import_volunteers "C:\Users\you\Documents\volunteers.csv" --save
  ```
  Nobody is emailed. Record each person's training in the app (Training, or their page), then use **Email a new welcome link** on their page when they're ready to start. Running it again skips anyone already added, so it's safe to repeat with new rows.

- Problem alerts (from Phase 9): they go to your Admin account's email. To send them somewhere else, set `PROBLEM_EMAILS` in Render (comma-separated). Check they arrive with **Admin → Problems → Send me a test alert**.
- Clean up old page visits and problems (the pilot runs this daily):
  ```powershell
  .venv\Scripts\python manage.py prune_usage
  ```

Close the window when you're done, so the settings don't linger. `DEBUG` here only affects the command on your computer, not the site.

## 4. Gmail (sends the app's emails)

Hosts block the usual mail ports (Render's free plan since September 2025, and Railway's Hobby plan), so the app sends through **Gmail's web API** instead. It's free, and emails still come from the app's Gmail address. The setup is one-time, about 20–30 minutes. Google renames its screens now and then, so a button may be worded slightly differently.

**A. In Google (signed in as the app's Gmail account)**

1. Go to https://console.cloud.google.com and create a project, for example "Shelter Calendar".
2. **Turn on the Gmail API:** Menu → APIs & Services → Library → search "Gmail API" → **Enable**.
3. **Describe the app:** Menu → Google Auth platform → Branding → **Get started**. Give it a name (for example "Shelter volunteer schedule"), choose the Gmail address as the support email, choose **External**, enter the Gmail address again as the contact, agree and **Create**.
4. **Make it permanent:** Google Auth platform → Audience → **Publish app** (so its status is "In production"). Left on "Testing", Google cancels the authorization after 7 days. No review is needed for this.
5. **Create the key:** Google Auth platform → Clients → **Create client** → Application type **Desktop app** → Create. Keep the page open: it shows a **Client ID** and a **Client secret**.

**B. On your PC (PowerShell, in the project folder)**

6. Put the two values in the window (paste your own between the quotes), plus the Gmail address:
   ```powershell
   $env:GMAIL_CLIENT_ID = "the Client ID"
   $env:GMAIL_CLIENT_SECRET = "the Client secret"
   $env:EMAIL_HOST_USER = "the app's Gmail address"
   $env:DEBUG = "1"
   ```
7. Authorize, and send yourself a test:
   ```powershell
   .venv\Scripts\python manage.py gmail_authorize --send-test-to you@example.com
   ```
   Your browser opens. Sign in as **the app's Gmail account** and choose **Allow**. Google will say it hasn't verified the app: choose **Advanced**, then **Go to … (unsafe)**. That warning is expected, because the app is yours and only you use it. The app only asks for permission to *send* email; it can't read the mailbox.
8. Back in PowerShell it prints `GMAIL_REFRESH_TOKEN=…`, and the test email should arrive within a minute.

**C. On the host (Render now, Railway for the pilot)**

9. In the service's Environment, add three values: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` and `GMAIL_REFRESH_TOKEN`. Keep `EMAIL_HOST_USER` set to the Gmail address (it's the "From" address). `EMAIL_HOST_PASSWORD` is no longer used and can be removed.
10. Save, let it redeploy, then check on the site: **Admin → Problems → Send me a test alert**.

Treat the client secret and the refresh token like passwords: don't email them, paste them into chats, or commit them.

**If emails stop later:** the Problems page will show SC-501 saying the authorization is no longer accepted. That happens if the Gmail account's password changes or access is removed in the Google account. Repeat steps 6–9 (the Google steps don't need redoing).

**Until this is set up**, or if someone's email can't be reached, print their PIN link and pass it on yourself:

```powershell
.venv\Scripts\python manage.py setup_link "First Last"
```

## 5. GitHub

Secret scanning and push protection are already on. Never commit `.env`; it's in `.gitignore`.
