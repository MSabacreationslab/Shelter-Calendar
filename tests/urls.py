"""The real URLs plus views that fail on purpose, for testing the error pages."""

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_POST

from config import urls as project_urls


def boom(request):
    """Raise an unexpected error."""
    raise RuntimeError("Deliberate failure for the 500 page test")


def forbidden(request):
    """Refuse access."""
    raise PermissionDenied


def bad(request):
    """Reject a malformed request."""
    raise SuspiciousOperation("Deliberate bad request")


@require_POST
def form_post(request):
    """Accept a form post (CSRF-protected by middleware)."""
    return HttpResponse("ok")


urlpatterns = [
    *project_urls.urlpatterns,
    path("test/boom/", boom),
    path("test/forbidden/", forbidden),
    path("test/bad/", bad),
    path("test/form/", form_post),
]

handler400 = project_urls.handler400
handler403 = project_urls.handler403
handler404 = project_urls.handler404
handler500 = project_urls.handler500
