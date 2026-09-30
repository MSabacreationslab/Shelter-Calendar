"""Writing to the change log. Every action has a plain-language description for staff."""

from django.utils import timezone

from core.models import AuditEvent

ACTIONS = {
    "account.created": "Account created",
    "account.pin_set": "Set their PIN",
    "account.locked_out": "Locked out for 15 minutes after too many wrong PINs",
    "account.needs_new_link": "Locked until they get a new setup link",
    "setup_link.sent": "Setup link sent",
}


def record(
    action, *, actor=None, target_user=None, target_repr="", at=None, **details
) -> AuditEvent:
    """Add one entry to the change log. Call inside the same transaction as the change."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown change-log action: {action}")
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        target_repr=target_repr or (str(target_user) if target_user else ""),
        details=details,
        created_at=at or timezone.now(),
    )


def describe(event: AuditEvent) -> str:
    """The plain-language description shown in the change log."""
    return ACTIONS.get(event.action, event.action)
