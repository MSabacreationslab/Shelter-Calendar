"""Who can do what (SPEC §3). Role names appear here and nowhere else in the rules."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from accounts.models import Role

# Not capabilities: markers for pages anyone can open, or anyone signed in.
PUBLIC = "public"
SIGNED_IN = "signed_in"

VOLUNTEER = frozenset(
    {
        "view_own_schedule",
        "edit_own_contact",
        "sign_up_self",
        "cancel_own_signup",
    }
)
STAFF = VOLUNTEER | {
    "view_dashboard",
    "view_full_schedule",
    "view_contacts",
    "view_as_volunteer",
    "view_change_log",
    "manage_shifts",
    "assign_volunteers",
    "manage_waitlist",
    "approve_signups",
    "record_training",
    "manage_trainings",
    "add_volunteers",
    "edit_volunteers",
    "reset_volunteer_pin",
    "view_reports",
    "manage_staff",
}
# The Admin's own tools: shelter settings, and the Usage, Hotspots and Problems pages.
ADMIN = STAFF | {"edit_settings", "view_usage"}

ROLE_CAPABILITIES = {
    Role.VOLUNTEER: VOLUNTEER,
    Role.STAFF: STAFF,
    Role.ADMIN: ADMIN,
}
ALL_CAPABILITIES = ADMIN


def has_capability(user, capability: str) -> bool:
    """True if this person, as signed in right now, may do this."""
    if capability not in ALL_CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability}")
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    return capability in ROLE_CAPABILITIES.get(user.role, frozenset())


def requires(capability: str):
    """Declare what a view needs. Every URL in the app must use this (see the matrix test)."""
    if capability not in (PUBLIC, SIGNED_IN) and capability not in ALL_CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability}")

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if capability != PUBLIC:
                if not request.user.is_authenticated:
                    return redirect_to_login(request.get_full_path())
                if capability != SIGNED_IN and not has_capability(request.user, capability):
                    raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapped.required_capability = capability
        return wrapped

    return decorator
