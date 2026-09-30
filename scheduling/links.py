"""Signed links in emails that work without signing in."""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.urls import reverse

CONFLICT_SALT = "orientation-conflict"
CONFLICT_LINK_LIFETIME = timedelta(days=60)


def conflict_token(signup) -> str:
    """The signed value in the welcome email's "this time doesn't work" link."""
    return signing.dumps({"signup": signup.pk}, salt=CONFLICT_SALT)


def conflict_url(signup) -> str:
    """The full address of that link."""
    path = reverse("scheduling:orientation_conflict", args=[conflict_token(signup)])
    return settings.SITE_URL.rstrip("/") + path


def signup_from_conflict_token(token: str) -> int:
    """The signup id in a valid token. Raises signing.BadSignature if forged or too old."""
    data = signing.loads(token, salt=CONFLICT_SALT, max_age=CONFLICT_LINK_LIFETIME)
    return int(data["signup"])
