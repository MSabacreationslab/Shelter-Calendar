"""Who can take which shift (SPEC §5). The only place this is decided."""

from django.db.models import Q
from django.utils import timezone

from scheduling.models import ShiftKind, ShiftStatus
from training.models import TrainingNeed, TrainingRecord

TURNED_OFF = "turned_off"
CANCELLED = "cancelled"
STARTED = "started"
NEEDS_TRAINING = "needs_training"
NEEDS_ORIENTATION = "needs_orientation"
SESSION_NOT_NEEDED = "session_not_needed"


def trained_type_ids(user) -> set[int]:
    """Training types this person has completed (voided records don't count)."""
    return set(
        TrainingRecord.objects.filter(volunteer=user, voided_at__isnull=True).values_list(
            "training_type_id", flat=True
        )
    )


def needed_type_ids(user) -> set[int]:
    """Training types staff have said this person still needs."""
    return set(
        TrainingNeed.objects.filter(volunteer=user, resolved_at__isnull=True).values_list(
            "training_type_id", flat=True
        )
    )


def may_take_untrained_shifts(user) -> bool:
    """Staff always may; volunteers once staff say so or they finish orientation."""
    if user.is_staff_member:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.no_training_eligible)


def why_not(user, shift, *, staff_adding=False, now=None) -> str | None:
    """The reason this person can't take this shift, or None if they can."""
    now = now or timezone.now()
    if not user.is_active:
        return TURNED_OFF
    if shift.status != ShiftStatus.SCHEDULED:
        return CANCELLED
    if shift.starts_at <= now:
        return STARTED
    if shift.kind == ShiftKind.TRAINING:
        # Staff can put anyone in a session; volunteers join sessions they still need.
        if staff_adding or shift.teaches_id in needed_type_ids(user):
            return None
        return SESSION_NOT_NEEDED
    if shift.required_training_id:
        return None if shift.required_training_id in trained_type_ids(user) else NEEDS_TRAINING
    return None if may_take_untrained_shifts(user) else NEEDS_ORIENTATION


def can_take(user, shift, **kwargs) -> bool:
    """True if this person may take this shift."""
    return why_not(user, shift, **kwargs) is None


def eligible_filter(user) -> Q:
    """A queryset filter for shifts this person could take, ignoring whether they're full."""
    allowed = Q(kind=ShiftKind.REGULAR, required_training__in=trained_type_ids(user))
    allowed |= Q(kind=ShiftKind.TRAINING, teaches__in=needed_type_ids(user))
    if may_take_untrained_shifts(user):
        allowed |= Q(kind=ShiftKind.REGULAR, required_training__isnull=True)
    return allowed & Q(status=ShiftStatus.SCHEDULED, starts_at__gt=timezone.now())
