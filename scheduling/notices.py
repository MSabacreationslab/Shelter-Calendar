"""Emails about shifts. Each runs after the change is saved (see services)."""

import logging

from core.models import ShelterSettings
from core.templatetags.formatting import clock_text, long_date
from notifications import email

logger = logging.getLogger(__name__)


def describe(shift) -> str:
    """Dog walking, Tuesday, October 6, 9:00 AM – 11:00 AM (plain text, for emails)."""
    times = f"{clock_text(shift.starts_at)} – {clock_text(shift.ends_at)}"
    return f"{shift.title}, {long_date(shift.starts_at)}, {times}"


def _to_staff(template, context):
    addresses = ShelterSettings.load().notify_email_list
    if not addresses:
        logger.warning("No notification emails set; %s not sent", template)
    for address in addresses:
        email.send(template, to=address, context=context)


def late_cancellation(signup):
    """Tell staff straight away when someone can't make a shift that's coming up soon."""
    _to_staff(
        "late_cancellation",
        {
            "person": signup.volunteer,
            "shift": describe(signup.shift),
            "reason": signup.cancel_reason,
        },
    )


def orientation_conflict(signup):
    """Tell staff a new volunteer can't make their orientation time."""
    _to_staff("orientation_conflict", {"person": signup.volunteer, "shift": describe(signup.shift)})


def promoted_from_waitlist(signup):
    """Good news for the volunteer: they're on the shift now."""
    email.send(
        "waitlist_promoted",
        to=signup.volunteer.email,
        related_user=signup.volunteer,
        context={"person": signup.volunteer, "shift": describe(signup.shift)},
    )


def shift_cancelled(signup, reason):
    """Let each signed-up volunteer know the shift won't happen."""
    email.send(
        "shift_cancelled",
        to=signup.volunteer.email,
        related_user=signup.volunteer,
        context={"person": signup.volunteer, "shift": describe(signup.shift), "reason": reason},
    )
