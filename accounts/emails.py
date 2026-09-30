"""Emails about signing in."""

from accounts.models import SetupLinkPurpose
from accounts.services import setup_link_url
from notifications import email


def send_setup_email(user, token: str, purpose: str):
    """The welcome email for new people, or the new-PIN email for everyone else."""
    template = "welcome" if purpose == SetupLinkPurpose.INVITE else "new_pin"
    return email.send(
        template,
        to=user.email,
        related_user=user,
        context={"person": user, "link": setup_link_url(token)},
    )
