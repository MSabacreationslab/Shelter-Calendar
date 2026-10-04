"""Pages that belong to the whole site: home, health check, style guide and error pages."""

import logging

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from accounts.permissions import PUBLIC, SIGNED_IN, has_capability, requires
from core import errors
from core.context_processors import VOLUNTEER_VIEW, in_volunteer_view
from core.forms import StyleguideForm, post_data

logger = logging.getLogger(__name__)


@requires(SIGNED_IN)
def home(request):
    """Volunteers land on their shift calendar; staff on their dashboard, unless they've
    switched to the volunteer view."""
    if has_capability(request.user, "view_dashboard") and not in_volunteer_view(request):
        from dashboard.views import dashboard

        return dashboard(request)
    from scheduling.volunteer_views import my_shifts

    return my_shifts(request)


@requires("view_dashboard")
@require_POST
def switch_view(request):
    """Staff flip between their own view and the volunteer view. It changes the menu and
    home page only: permissions and booking rules are untouched."""
    if request.POST.get("to") == "volunteer":
        request.session[VOLUNTEER_VIEW] = True
    else:
        request.session.pop(VOLUNTEER_VIEW, None)
    return redirect("home")


@requires(PUBLIC)
def healthz(request):
    """Tell the host the app is running. Deliberately skips the database."""
    return JsonResponse({"status": "ok"})


SWATCHES = [
    ("background", "Page background"),
    ("surface", "Cards and forms"),
    ("text-primary", "Text and main buttons"),
    ("text-secondary", "Supporting text"),
    ("border", "Card edges and dividers"),
    ("border-strong", "Form field edges"),
    ("staff", "Staff"),
    ("staff-soft", "Staff highlight"),
    ("volunteer", "Volunteers and open shifts"),
    ("volunteer-soft", "Volunteer highlight"),
    ("success", "Confirmed and done"),
    ("warning", "Waiting and needs attention"),
    ("danger", "Errors and removing things"),
    ("focus", "Keyboard focus ring"),
]


@requires(PUBLIC)
def styleguide(request):
    """Every component in one place, for checking the design by eye on the test site."""
    if not (settings.DEBUG or settings.DEMO_MODE):
        raise Http404
    form = StyleguideForm(post_data(request))
    submitted = request.method == "POST" and form.is_valid()
    return render(
        request,
        "core/styleguide.html",
        {
            "form": form,
            "submitted": submitted,
            "swatches": SWATCHES,
            "sample_staff": User(role=Role.STAFF),
            "sample_volunteer": User(role=Role.VOLUNTEER),
        },
    )


def _error_page(request, error: errors.ErrorCode, status: int, summary="") -> HttpResponse:
    """Record the problem (and alert the Admin), then show a short, friendly page.

    Falls back to plain HTML if even the page fails.
    """
    from insights import problems

    told = problems.report(error, request=request, status=status, summary=summary)
    ref = getattr(request, "ref", "-")
    context = {"error": error, "ref": ref, "admin_told": told}
    try:
        return render(request, "errors/error.html", context, status=status)
    except Exception:
        # The error page must never raise; a bare page still gives the code and reference.
        logger.exception("Error page failed to render for %s", error.code)
        body = render_to_string("errors/fallback.html", context)
        return HttpResponse(body, status=status)


def bad_request(request, exception=None):
    """400: the request didn't make sense."""
    return _error_page(request, errors.BAD_REQUEST, 400, summary=str(exception or "")[:300])


def permission_denied(request, exception=None):
    """403: the person isn't allowed to see this page."""
    return _error_page(request, errors.NOT_ALLOWED, 403)


def page_not_found(request, exception=None):
    """404: no such page."""
    return _error_page(request, errors.PAGE_NOT_FOUND, 404, summary=f"Nothing at {request.path}")


def server_error(request):
    """500: something broke on our side."""
    return _error_page(request, errors.SERVER_ERROR, 500)


def csrf_failure(request, reason=""):
    """403 from a stale or missing form token, usually a page left open too long."""
    logger.warning("Form check failed: %s", reason)
    return _error_page(request, errors.FORM_EXPIRED, 403, summary=reason)
