"""Error codes people can see on screen (SC-###).

A code plus the request reference is enough to find the problem in the logs
from a screenshot or a phone call. Never renumber or reuse a code; add new ones
at the end of their range and document them in docs/error-codes.md.

Ranges: SC-1xx general pages, SC-2xx sign-in and accounts, SC-3xx scheduling,
SC-4xx training, SC-5xx email and reports.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    """One on-screen error: its code, a short title and a plain-language message."""

    code: str
    title: str
    message: str


BAD_REQUEST = ErrorCode(
    "SC-101",
    "Something went wrong",
    "Please go back and try again.",
)
NOT_ALLOWED = ErrorCode(
    "SC-102",
    "You can't open this page",
    "This page is only for certain people. If you think you should see it, "
    "please contact the volunteer team.",
)
PAGE_NOT_FOUND = ErrorCode(
    "SC-103",
    "We can't find that page",
    "It may have moved, or the link may have a typo. Try the home page instead.",
)
SERVER_ERROR = ErrorCode(
    "SC-104",
    "Something went wrong",
    "Please try again in a minute.",
)
FORM_EXPIRED = ErrorCode(
    "SC-105",
    "This page was open too long",
    "Please go back, refresh the page, and try again.",
)

LINK_EXPIRED = ErrorCode(
    "SC-201",
    "This link has expired",
    "Links for choosing a PIN work once and last 7 days. Please ask the volunteer team "
    "to send you a new one.",
)

ALL_ERRORS = [BAD_REQUEST, NOT_ALLOWED, PAGE_NOT_FOUND, SERVER_ERROR, FORM_EXPIRED, LINK_EXPIRED]
