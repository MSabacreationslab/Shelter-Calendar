"""Count page visits for the Admin's usage and hotspot pages."""

import logging
import time
from urllib.parse import urlsplit

from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)

# Not worth counting: the host's health check, the style guide and the emergency backend.
SKIP_ROUTES = {"healthz", "styleguide"}
SKIP_PREFIXES = ("admin:",)


def device_of(user_agent: str) -> str:
    """phone, tablet or computer, from the browser's description of itself."""
    agent = user_agent or ""
    if "iPad" in agent or "Tablet" in agent or ("Android" in agent and "Mobile" not in agent):
        return "tablet"
    if "Mobi" in agent or "iPhone" in agent or "Android" in agent:
        return "phone"
    return "computer"


def _came_from(request) -> str:
    referer = request.headers.get("Referer", "")
    if not referer:
        return ""
    parts = urlsplit(referer)
    if parts.netloc and parts.netloc != request.get_host():
        return "elsewhere"
    try:
        return resolve(parts.path).view_name
    except Resolver404:
        return ""


def _form_problem(request, response) -> bool:
    # Forms that worked redirect; one sent back with a field to fix marks it aria-invalid.
    if request.method != "POST" or response.status_code != 200 or response.streaming:
        return False
    return b'aria-invalid="true"' in response.content


class UsageMiddleware:
    """Record one PageView per request to a page of the app. Never breaks the page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """Time the request, then record it."""
        started = time.monotonic()
        response = self.get_response(request)
        try:
            self._record(request, response, started)
        except Exception:
            logger.warning("Couldn't record a page visit", exc_info=True)
        return response

    def _record(self, request, response, started):
        match = getattr(request, "resolver_match", None)
        if match is None or match.view_name in SKIP_ROUTES:
            return
        if match.view_name.startswith(SKIP_PREFIXES):
            return
        from insights.models import PageView

        user = getattr(request, "user", None)
        signed_in = bool(user and user.is_authenticated)
        PageView.objects.create(
            user=user if signed_in else None,
            role=user.role if signed_in else "",
            route=match.view_name[:100],
            method=request.method[:8],
            status=response.status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            device=device_of(request.headers.get("User-Agent", "")),
            came_from=_came_from(request)[:100],
            form_problem=_form_problem(request, response),
        )
