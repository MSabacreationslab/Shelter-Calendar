"""Pages that belong to the whole site: home, health check, style guide and error pages."""

import logging

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from accounts.permissions import PUBLIC, SIGNED_IN, has_capability, requires
from core import errors
from core.forms import StyleguideForm, post_data

logger = logging.getLogger(__name__)


@requires(SIGNED_IN)
def home(request):
    """Volunteers land on their shift calendar; staff on their home page."""
    if not has_capability(request.user, "view_dashboard"):
        from scheduling.volunteer_views import my_shifts

        return my_shifts(request)
    return render(request, "core/home.html")


@requires(PUBLIC)
def healthz(request):
    """Tell the host the app is running. Deliberately skips the database."""
    return JsonResponse({"status": "ok"})


@requires(PUBLIC)
def styleguide(request):
    """Every component in one place, for checking the design by eye on the test site."""
    if not (settings.DEBUG or settings.DEMO_MODE):
        raise Http404
    form = StyleguideForm(post_data(request))
    submitted = request.method == "POST" and form.is_valid()
    return render(request, "core/styleguide.html", {"form": form, "submitted": submitted})


def _error_page(request, error: errors.ErrorCode, status: int) -> HttpResponse:
    """Render the friendly error page, falling back to plain HTML if even that fails."""
    ref = getattr(request, "ref", "-")
    context = {"error": error, "ref": ref}
    try:
        return render(request, "errors/error.html", context, status=status)
    except Exception:
        # The error page must never raise; a bare page still gives the code and reference.
        logger.exception("Error page failed to render for %s", error.code)
        body = render_to_string("errors/fallback.html", context)
        return HttpResponse(body, status=status)


def bad_request(request, exception=None):
    """400: the request didn't make sense."""
    return _error_page(request, errors.BAD_REQUEST, 400)


def permission_denied(request, exception=None):
    """403: the person isn't allowed to see this page."""
    return _error_page(request, errors.NOT_ALLOWED, 403)


def page_not_found(request, exception=None):
    """404: no such page."""
    return _error_page(request, errors.PAGE_NOT_FOUND, 404)


def server_error(request):
    """500: something broke on our side."""
    return _error_page(request, errors.SERVER_ERROR, 500)


def csrf_failure(request, reason=""):
    """403 from a stale or missing form token, usually a page left open too long."""
    logger.warning("Form check failed: %s", reason)
    return _error_page(request, errors.FORM_EXPIRED, 403)
