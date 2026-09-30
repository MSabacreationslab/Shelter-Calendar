# Error codes

Every error someone can see shows a code (`SC-###`) and a six-character reference. With both, the matching log line can be found: search the logs for `ref=<reference>`.

Codes live in `core/errors.py`. Never renumber or reuse a code. Add new ones at the end of their range and document them here.

| Range | Area |
|---|---|
| SC-1xx | General pages |
| SC-2xx | Sign-in and accounts |
| SC-3xx | Scheduling |
| SC-4xx | Training |
| SC-5xx | Email and reports |

## SC-1xx: General pages

| Code | Shown as | What happened | What to check |
|---|---|---|---|
| SC-101 | Something went wrong | The request was malformed (HTTP 400), e.g. a tampered form or a bad host header. | Logs for `ref=`; usually a bot or an old bookmark. |
| SC-102 | You can't open this page | The person isn't allowed to see the page (HTTP 403). | Their role and the page's capability (SPEC §3). |
| SC-103 | We can't find that page | No such page (HTTP 404). | The link they followed; an old email link to something that was removed. |
| SC-104 | Something went wrong | An unexpected error (HTTP 500). | The traceback in the logs next to `ref=`. |
| SC-105 | This page was open too long | The form's security check failed (CSRF), usually because the page was left open, cookies were cleared, or the form was sent twice from an old tab. | Logs show the reason. If it's frequent for one person, check their browser blocks cookies. |
