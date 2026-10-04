"""Template context shared by every page."""

import logging
import re

from django.conf import settings
from django.db import DatabaseError

from accounts.permissions import has_capability
from core.phones import format_phone, normalize_phone

logger = logging.getLogger(__name__)

# Pages under these URL namespaces sit behind the Admin menu item (people too, except
# My profile, which the menu handles itself).
ADMIN_AREAS = ("scheduling", "training", "reports", "dashboard", "insights")
# The session key for staff looking at the volunteer view.
VOLUNTEER_VIEW = "volunteer_view"


def _shown(phone: str) -> str:
    """Settings keep the number as typed; show "(614) 555-0100" however it was entered."""
    try:
        return format_phone(normalize_phone(phone))
    except ValueError:
        return phone


def shelter_details() -> dict:
    """Name and contact details from the settings row, or env defaults if the database is down."""
    from core.models import ShelterSettings

    try:
        row = ShelterSettings.load()
        name, phone, email = row.shelter_name, row.shelter_phone, row.shelter_email
    except DatabaseError:
        # Error pages must still render when the database is the problem.
        logger.warning("Shelter settings unavailable; using environment defaults")
        name, phone, email = settings.SHELTER_NAME, settings.SHELTER_PHONE, settings.SHELTER_EMAIL
    return {
        "name": name,
        "phone": _shown(phone),
        # tel: links need digits only, or phones won't dial them.
        "phone_link": re.sub(r"[^\d+]", "", phone),
        "email": email,
    }


def in_volunteer_view(request) -> bool:
    """Staff who've switched to seeing the menu and home page the way volunteers do.

    It only changes what's shown. What they're allowed to do, and the booking rules for
    staff, stay the same.
    """
    session = getattr(request, "session", None)
    if not session or not session.get(VOLUNTEER_VIEW):
        return False
    return has_capability(getattr(request, "user", None), "view_dashboard")


def shelter(request):
    """The shelter's name and contact details, shown in the header and footer."""
    details = getattr(request, "_shelter_details", None)
    if details is None:
        details = request._shelter_details = shelter_details()
    return {
        "shelter": details,
        "demo_mode": settings.DEMO_MODE,
        "admin_areas": ADMIN_AREAS,
        "volunteer_view": in_volunteer_view(request),
    }
