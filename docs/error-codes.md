# Error codes

Every problem the app records gets a code (`SC-###`). People only see a short, plain message ("Something went wrong. We've let the admin know automatically") and a six-character reference. The code and the details go to the Admin.

- **Problems page** (`/admin/problems/`, Admin only): every recorded problem, newest first, with the person, the page, the reference and, for server errors, the traceback. It also has **Send me a test alert**.
- **Email alerts** go to `PROBLEM_EMAILS` (a comma-separated list in the environment) or, if that's empty, every active Admin's email. You're emailed about:
  - anything that happened to a signed-in person
  - every server error (SC-104), even for someone signed out
  - every failed scheduled task (SC-106) and failed email (SC-501)
- **Not emailed**, only recorded: 400, 403 and 404 for people who aren't signed in. Bots probe public sites constantly, and those alerts would bury the real ones.
- **At most one email an hour** for the same code on the same page. The Problems page still lists every time it happened.
- To match a phone call to a problem, search the Problems page or the logs for the reference (`ref=<reference>`).

Codes live in `core/errors.py` (`admin_note` is the text in the alert). Never renumber or reuse a code. Add new ones at the end of their range and document them here.

| Range | Area |
|---|---|
| SC-1xx | General pages and scheduled tasks |
| SC-2xx | Sign-in and accounts |
| SC-3xx | Scheduling |
| SC-4xx | Training |
| SC-5xx | Email and reports |

## SC-1xx: General pages and scheduled tasks

| Code | People see | What happened | What to check |
|---|---|---|---|
| SC-101 | Something went wrong | The request was malformed (HTTP 400), e.g. a tampered form or a bad host header. | Usually a bot or an old bookmark. |
| SC-102 | You can't open this page | The person isn't allowed to see the page (HTTP 403). | Their role and the page's capability (SPEC §3); the link they followed. |
| SC-103 | We can't find that page | No such page (HTTP 404). | If a signed-in person hit it, a link in the app or an email may be broken. |
| SC-104 | Something went wrong | An unexpected error (HTTP 500). | The traceback in the alert and on the Problems page. |
| SC-105 | This page was open too long | The form's security check failed (CSRF), usually because the page was left open, cookies were cleared, or the form was sent twice from an old tab. | If it's frequent for one person, check whether their browser blocks cookies. |
| SC-106 | (nothing; it runs in the background) | A scheduled command (reminders, digests, clean-ups) stopped with an error. | Its emails may not have gone out. Fix it, then run the command again by hand. |
| SC-107 | (nothing) | A test alert sent from the Problems page. | Nothing is wrong. |

## SC-2xx: Sign-in and accounts

| Code | People see | What happened | What to check |
|---|---|---|---|
| SC-201 | This link has expired | A setup link was opened after 7 days, after it was used, after a newer link replaced it, or for a turned-off account. This is expected, so it isn't recorded as a problem. | The person's setup links in the backend. Send a new one. |

## SC-5xx: Email and reports

| Code | People see | What happened | What to check |
|---|---|---|---|
| SC-501 | (nothing; staff see the failed email on the person's page) | The mail server refused or timed out. The change that triggered the email was still saved. | The Gmail app password in Render (`EMAIL_HOST_PASSWORD`). If Gmail itself is down, the alert can't be emailed either, but it's on the Problems page. |
