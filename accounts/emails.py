"""Emails about signing in."""

from accounts.models import SetupLinkPurpose
from accounts.services import setup_link_url
from notifications import email


def send_setup_email(user, token: str, purpose: str, *, orientation_signup=None):
    """The welcome email for new people, or the new-PIN email for everyone else."""
    template = "welcome" if purpose == SetupLinkPurpose.INVITE else "new_pin"
    context = {"person": user, "link": setup_link_url(token)}
    if orientation_signup is not None:
        from scheduling import links, notices

        context["orientation"] = {
            "when": notices.describe(orientation_signup.shift),
            "conflict_link": links.conflict_url(orientation_signup),
        }
    return email.send(template, to=user.email, related_user=user, context=context)
