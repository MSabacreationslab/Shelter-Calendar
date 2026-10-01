"""Recording problems and emailing the Admin about them.

Every problem is kept on the Problems page. The Admin is emailed about anything that
happened to a signed-in person, every server error, and every failed task or email.
Signed-out 400/403/404s are only recorded: bots probe public sites all day.
The same problem on the same page is emailed at most once an hour.

Nothing here may raise: reporting a problem must never cause another one.
"""

import logging
import sys
import traceback
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core import errors
from core.templatetags.formatting import clock_text, long_date

logger = logging.getLogger(__name__)

QUIET_PERIOD = timedelta(hours=1)


def remember_exception(sender, request=None, **kwargs):
    """Signal receiver: keep the exception so the 500 page can report its traceback."""
    if request is not None:
        request._problem_exc_info = sys.exc_info()


def recipients() -> list[str]:
    """PROBLEM_EMAILS if set, otherwise every active Admin's email."""
    if settings.PROBLEM_EMAILS:
        return list(settings.PROBLEM_EMAILS)
    from accounts.models import Role, Status, User

    return list(
        User.objects.filter(role=Role.ADMIN, status=Status.ACTIVE)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def _request_details(request) -> dict:
    user = getattr(request, "user", None)
    signed_in = bool(user and user.is_authenticated)
    match = getattr(request, "resolver_match", None)
    return {
        "ref": getattr(request, "ref", ""),
        "route": match.view_name if match else "",
        "path": request.path[:200],
        "method": request.method or "",
        "user": user if signed_in else None,
        "role": user.role if signed_in else "",
    }


def _worth_emailing(status, details) -> bool:
    if status is None or status >= 500:
        return True  # server errors, failed tasks and emails, test alerts
    return details.get("user") is not None


def _recently_emailed(code, route) -> bool:
    from insights.models import Problem

    return Problem.objects.filter(
        code=code, route=route, emailed=True, at__gte=timezone.now() - QUIET_PERIOD
    ).exists()


def report(
    error: errors.ErrorCode,
    *,
    request=None,
    status: int | None = None,
    summary: str = "",
    details: str = "",
    route: str = "",
    always: bool = False,
) -> bool:
    """Record a problem and email the Admin if it's worth it (`always` skips the quiet hour).

    Returns True when the Admin knows: emailed now, or about the same problem within the hour.
    """
    try:
        info = _request_details(request) if request is not None else {"route": route}
        exc_info = getattr(request, "_problem_exc_info", None) if request is not None else None
        if exc_info and exc_info[0] is not None:
            details = details or "".join(traceback.format_exception(*exc_info))
            summary = summary or f"{exc_info[0].__name__}: {exc_info[1]}"
        problem = _save(error, status, summary, details, info)
        if not _worth_emailing(status, info):
            return False
        if (
            not always
            and problem is not None
            and _recently_emailed(error.code, info.get("route", ""))
        ):
            return True
        emailed = _send(error, status, summary, details, info)
        if emailed and problem is not None:
            problem.emailed = True
            problem.save(update_fields=["emailed"])
        return emailed
    except Exception:
        logger.exception("Couldn't report problem %s", error.code)
        return False


def _save(error, status, summary, details, info):
    """Keep the problem for the Problems page. If the database is the problem, skip it."""
    from insights.models import Problem

    try:
        return Problem.objects.create(
            code=error.code,
            status=status,
            ref=info.get("ref", ""),
            route=info.get("route", ""),
            path=info.get("path", ""),
            method=info.get("method", ""),
            user=info.get("user"),
            role=info.get("role", ""),
            summary=summary[:300],
            details=details,
        )
    except Exception:
        logger.exception("Couldn't save problem %s", error.code)
        return None


def _send(error, status, summary, details, info) -> bool:
    try:
        to = recipients()
    except Exception:
        logger.exception("Couldn't look up who to email about %s", error.code)
        to = []
    if not to:
        logger.warning("Problem %s not emailed: no Admin email set", error.code)
        return False
    where = info.get("route") or "a scheduled task"
    ref = info.get("ref", "")
    subject = f"[Shelter app] {error.code} {error.title}: {where}" + (
        f" (ref {ref})" if ref else ""
    )
    user = info.get("user")
    now = timezone.localtime()
    facts = [f"When: {long_date(now)} at {clock_text(now)}"]
    if info.get("method"):
        who = f"{user.get_full_name()} ({user.get_role_display()})" if user else "Not signed in"
        facts += [f"Who: {who}", f"Page: {where} ({info['method']} {info['path']})"]
    else:
        facts.append(f"Where: {where}")
    if status:
        facts.append(f"Status: {status}")
    if ref:
        facts.append(f"Reference: {ref}")
    if summary:
        facts.append(f"What happened: {summary}")
    body = "\n\n".join(
        [
            f"{error.code}: {error.title}",
            error.admin_note,
            "\n".join(facts),
            f"All problems: {settings.SITE_URL}/admin/problems/",
        ]
    )
    if details:
        # The end of a traceback is the useful part.
        body += f"\n\nDetails:\n{details[-6000:]}"
    try:
        send_mail(subject[:200], body, settings.DEFAULT_FROM_EMAIL, to, fail_silently=False)
    except Exception:
        logger.exception("Couldn't email the Admin about %s", error.code)
        return False
    return True
