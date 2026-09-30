"""Writing to the change log. Every action has a plain-language description for staff."""

from django.utils import timezone

from core.models import AuditEvent

ACTIONS = {
    "account.created": "Account created",
    "account.pin_set": "Set their PIN",
    "account.locked_out": "Locked out for 15 minutes after too many wrong PINs",
    "account.needs_new_link": "Locked until they get a new setup link",
    "setup_link.sent": "Setup link sent",
    "volunteer.edited": "Details updated",
    "profile.updated": "Updated their own contact details",
    "skill.added": "Skill added to the list",
    "skill.renamed": "Skill renamed",
    "skill.turned_off": "Skill taken off the list",
    "skill.turned_on": "Skill put back on the list",
    "shift.signed_up": "Signed up for a shift",
    "shift.added_by_staff": "Added to a shift by staff",
    "shift.cancelled": "Cancelled their shift",
    "shift.removed_by_staff": "Taken off a shift by staff",
    "shift.created": "Shift added",
    "shift.edited": "Shift changed",
    "shift.cancelled_by_staff": "Shift cancelled",
    "waitlist.joined": "Joined a waitlist",
    "waitlist.left": "Left a waitlist",
    "waitlist.removed": "Taken off a waitlist by staff",
    "schedule.filled": "Schedule filled in",
    "template.added": "Template week added",
    "pattern.added": "Repeating shift added",
    "pattern.edited": "Repeating shift changed",
    "pattern.ended": "Repeating shift stopped",
    "blackout.added": "Closed days added",
    "blackout.removed": "Closed days removed",
    "holiday.added": "Holiday added",
    "holiday.hidden": "Holiday hidden",
    "holiday.shown": "Holiday shown again",
    "holiday.removed": "Holiday removed",
    "orientation.conflict_reported": "Said their orientation time doesn't work",
    "training.recorded": "Training recorded",
    "training.voided": "Training record marked as a mistake",
    "training.need_added": "Training they need added",
    "training.need_removed": "Training they need removed",
    "training_type.added": "Training added to the list",
    "training_type.renamed": "Training renamed",
    "training_type.turned_off": "Training taken off the list",
    "training_type.turned_on": "Training put back on the list",
    "volunteer.no_training_changed": "Changed whether they can take no-training shifts",
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
