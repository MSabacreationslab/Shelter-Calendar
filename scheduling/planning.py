"""Building the schedule: template weeks, patterns, one-off shifts and blackouts."""

from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import audit
from scheduling.models import (
    BlackoutPeriod,
    Shift,
    ShiftPattern,
    ShiftStatus,
    SignupStatus,
    TemplateWeek,
)

PATTERN_COPY_FIELDS = [
    "title",
    "start_time",
    "end_time",
    "capacity",
    "kind",
    "teaches",
    "required_training",
    "notes",
]


@transaction.atomic
def add_template_week(name, *, by) -> TemplateWeek:
    """A named set of weekly shifts, such as "Regular week"."""
    week = TemplateWeek.objects.create(name=name)
    audit.record("template.added", actor=by, target_repr=name)
    return week


@transaction.atomic
def add_pattern(data: dict, *, by) -> ShiftPattern:
    """A repeating shift. Every-other-week patterns count weeks from their start date."""
    pattern = ShiftPattern.objects.create(**data, anchor_date=data["active_from"], created_by=by)
    audit.record("pattern.added", actor=by, target_repr=str(pattern))
    return pattern


def _future_shifts(pattern, now):
    return pattern.shifts.filter(starts_at__gt=now, status=ShiftStatus.SCHEDULED)


def _has_people(shift) -> bool:
    return shift.signups.exists() or shift.waitlist.exists()


@transaction.atomic
def update_pattern(pattern, data: dict, *, by, now=None) -> list[Shift]:
    """Change a pattern and its future shifts that nobody has touched.

    Shifts edited by hand or with people on them are left alone and returned
    so staff can review them (SPEC §6, "Edit a pattern").
    """
    now = now or timezone.now()
    for field, value in data.items():
        setattr(pattern, field, value)
    pattern.save()
    to_review = []
    for shift in _future_shifts(pattern, now):
        if shift.edited_by_hand or _has_people(shift):
            to_review.append(shift)
            continue
        for field in PATTERN_COPY_FIELDS:
            if field not in ("start_time", "end_time"):
                setattr(shift, field, getattr(pattern, field))
        shift.starts_at = timezone.make_aware(
            datetime.combine(shift.local_date, pattern.start_time)
        )
        shift.ends_at = timezone.make_aware(datetime.combine(shift.local_date, pattern.end_time))
        shift.save()
    audit.record("pattern.edited", actor=by, target_repr=str(pattern), fields=sorted(data))
    return to_review


@transaction.atomic
def end_pattern(pattern, last_day, *, by, now=None) -> list[Shift]:
    """Stop a pattern after `last_day`. Untouched empty shifts after it are removed; any with
    people on them stay and are returned for staff to deal with."""
    now = now or timezone.now()
    pattern.active_until = last_day
    pattern.save(update_fields=["active_until"])
    to_review = []
    for shift in _future_shifts(pattern, now).filter(local_date__gt=last_day):
        if shift.edited_by_hand or _has_people(shift):
            to_review.append(shift)
        else:
            # Never booked, never edited: removing it loses no history.
            shift.delete()
    audit.record("pattern.ended", actor=by, target_repr=str(pattern), last_day=str(last_day))
    return to_review


@transaction.atomic
def create_shift(data: dict, *, by) -> Shift:
    """A one-off shift, not from any pattern."""
    shift = Shift.objects.create(**data, created_by=by)
    audit.record("shift.created", actor=by, target_repr=str(shift))
    return shift


@transaction.atomic
def add_blackout(start, end, reason, *, by) -> tuple[BlackoutPeriod, list[Shift]]:
    """Mark days closed. Shifts already on those days are listed for staff, not cancelled."""
    blackout = BlackoutPeriod.objects.create(
        start_date=start, end_date=end, reason=reason, created_by=by
    )
    audit.record("blackout.added", actor=by, target_repr=str(blackout))
    return blackout, shifts_during(blackout)


def shifts_during(blackout) -> list[Shift]:
    """Scheduled shifts that fall inside a blackout."""
    return list(
        Shift.objects.filter(
            local_date__range=(blackout.start_date, blackout.end_date),
            status=ShiftStatus.SCHEDULED,
        ).order_by("starts_at")
    )


@transaction.atomic
def remove_blackout(blackout, *, by) -> None:
    """Reopen the days. Shifts skipped earlier can be added by filling again."""
    audit.record("blackout.removed", actor=by, target_repr=str(blackout))
    blackout.delete()


def shifts_in_range(start, end):
    """Shifts starting between two dates, with how many people are on each."""
    from django.db.models import Count

    return (
        Shift.objects.filter(local_date__range=(start, end))
        .annotate(
            filled=Count("signups", filter=Q(signups__status=SignupStatus.CONFIRMED)),
        )
        .select_related("required_training", "teaches")
        .order_by("starts_at", "title")
    )
