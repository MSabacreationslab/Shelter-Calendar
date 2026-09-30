"""Template context shared by every page."""

import re

from django.conf import settings


def shelter(request):
    """The shelter's name and contact details, shown in the header and footer."""
    phone = settings.SHELTER_PHONE
    return {
        "shelter": {
            "name": settings.SHELTER_NAME,
            "phone": phone,
            # tel: links need digits only, or phones won't dial them.
            "phone_link": re.sub(r"[^\d+]", "", phone),
            "email": settings.SHELTER_EMAIL,
        },
        "demo_mode": settings.DEMO_MODE,
    }
