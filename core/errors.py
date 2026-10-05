"""Error codes (SC-###) and what each one means.

People see a short, plain message and a reference; the Admin gets the code, what
happened and what to check by email (insights/problems.py). Never renumber or
reuse a code; add new ones at the end of their range and document them in
docs/error-codes.md.

Ranges: SC-1xx general pages and tasks, SC-2xx sign-in and accounts, SC-3xx
scheduling, SC-4xx training, SC-5xx email and reports.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    """One kind of problem: its code, what people see, and a note for the Admin."""

    code: str
    title: str
    message: str
    admin_note: str = ""


BAD_REQUEST = ErrorCode(
    "SC-101",
    "Something went wrong",
    "Please go back and try again.",
    "The request didn't make sense (HTTP 400): often a bot, a tampered form or an old bookmark.",
)
NOT_ALLOWED = ErrorCode(
    "SC-102",
    "You can't open this page",
    "This page is only for certain people. If you think you should see it, "
    "please contact the volunteer team.",
    "Someone opened a page their role can't use (HTTP 403). Check the link they followed "
    "and the page's capability (SPEC §3).",
)
PAGE_NOT_FOUND = ErrorCode(
    "SC-103",
    "We can't find that page",
    "The link may be old or have a typo. Please start again from the home page.",
    "No such page (HTTP 404). If a signed-in person hit it, a link in the app or an email "
    "may be broken.",
)
SERVER_ERROR = ErrorCode(
    "SC-104",
    "Something went wrong",
    "It wasn't anything you did. Please try again in a minute.",
    "An unexpected error (HTTP 500). The traceback is below and on the Problems page.",
)
FORM_EXPIRED = ErrorCode(
    "SC-105",
    "This page was open too long",
    "Please go back, reload the page, and try again.",
    "The form's security check failed (CSRF): usually a page left open, cleared cookies "
    "or a form sent twice from an old tab. Frequent for one person? Their browser may "
    "block cookies.",
)
TASK_FAILED = ErrorCode(
    "SC-106",
    "A scheduled task failed",
    "",
    "A management command (reminders, digests, clean-ups) stopped with an error. Its "
    "emails may not have gone out; run it again by hand once it's fixed.",
)
TEST_ALERT = ErrorCode(
    "SC-107",
    "Test alert",
    "",
    "Sent from the Problems page to check that alerts reach you. Nothing is wrong.",
)

LINK_EXPIRED = ErrorCode(
    "SC-201",
    "This link has expired",
    "Links for choosing a PIN work once and last 7 days. Please ask the volunteer team "
    "to send you a new one.",
)

EMAIL_FAILED = ErrorCode(
    "SC-501",
    "An email couldn't be sent",
    "",
    "Gmail refused the email or couldn't be reached. The change that triggered it was still "
    "saved; the person's page shows the failed email. What happened (below) says why; if the "
    "authorization is no longer accepted, run gmail_authorize again (docs/setup.md).",
)

ALL_ERRORS = [
    BAD_REQUEST,
    NOT_ALLOWED,
    PAGE_NOT_FOUND,
    SERVER_ERROR,
    FORM_EXPIRED,
    TASK_FAILED,
    TEST_ALERT,
    LINK_EXPIRED,
    EMAIL_FAILED,
]
BY_CODE = {error.code: error for error in ALL_ERRORS}
