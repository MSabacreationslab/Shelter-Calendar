"""The Admin's Usage, Hotspots and Problems pages (SPEC §6)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import requires
from core import errors
from insights import problems, queries


def _days(request):
    days = queries.period(request.GET.get("days"))
    return days, {"days": days, "periods": queries.PERIODS}


@requires("view_usage")
def usage(request):
    """Who used the app, how much, when and on what."""
    days, context = _days(request)
    return render(request, "insights/usage.html", {**context, **queries.usage(days)})


@requires("view_usage")
def hotspots(request):
    """What people do most, where they go next, and where they struggle."""
    days, context = _days(request)
    return render(request, "insights/hotspots.html", {**context, **queries.hotspots(days)})


@requires("view_usage")
def problem_list(request):
    """Every recorded problem, newest first."""
    days, context = _days(request)
    found = queries.problems(days)
    for row in found["by_code"]:
        known = errors.BY_CODE.get(row["code"])
        row["title"] = known.title if known else ""
    return render(
        request,
        "insights/problems.html",
        {**context, **found, "recipients": problems.recipients()},
    )


@requires("view_usage")
@require_POST
def test_alert(request):
    """Email the Admin a test alert, to check alerts arrive."""
    sent = problems.report(
        errors.TEST_ALERT, route="Problems page", summary="A test alert.", always=True
    )
    if sent:
        messages.success(request, "Test alert sent. Check your email.")
    else:
        messages.error(request, "The test alert couldn't be sent. Check the email settings.")
    return redirect("insights:problems")
