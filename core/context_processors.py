"""Template context shared by every page."""

import logging
import re

from django.conf import settings
from django.db import DatabaseError

from core.phones import format_phone, normalize_phone

logger = logging.getLogger(__name__)


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


def shelter(request):
    """The shelter's name and contact details, shown in the header and footer."""
    details = getattr(request, "_shelter_details", None)
    if details is None:
        details = request._shelter_details = shelter_details()
    return {"shelter": details, "demo_mode": settings.DEMO_MODE}
