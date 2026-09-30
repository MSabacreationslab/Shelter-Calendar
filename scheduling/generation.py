"""Filling the schedule from repeating patterns (SPEC §6, Phase 3).

Staff always see a preview first. Filling twice never duplicates a shift: the
database refuses a second shift from the same pattern on the same day.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import audit
from scheduling.holidays import holiday_label, holidays_between
from scheduling.models import BlackoutPeriod, Shift, ShiftPattern

MAX_FILL_WEEKS = 26


@dataclass
class PlannedShift:
    pattern: ShiftPattern
    day: date
    holiday: str = ""

    def starts_at(self) -> datetime:
        """Shelter-time start; 9:00 stays 9:00 across daylight-saving changes."""
        return timezone.make_aware(datetime.combine(self.day, self.pattern.start_time))

    def ends_at(self) -> datetime:
        """Shelter-time end."""
        return timezone.make_aware(datetime.combine(self.day, self.pattern.end_time))


@dataclass
class FillPlan:
    start: date
    end: date
    new: list[PlannedShift] = field(default_factory=list)
    already_there: int = 0
    blacked_out: list[PlannedShift] = field(default_factory=list)

    def holiday_days(self) -> list[tuple[date, str, int]]:
        """(day, holiday name, how many new shifts fall on it), for the Keep/Skip choices."""
        counts = Counter((p.day, p.holiday) for p in self.new if p.holiday)
        return sorted((day, name, count) for (day, name), count in counts.items())


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def runs_on(pattern: ShiftPattern, day: date) -> bool:
    """Whether the pattern has a shift on this day."""
    if day.weekday() != pattern.weekday:
        return False
    if day < pattern.active_from or (pattern.active_until and day > pattern.active_until):
        return False
    if pattern.every_n_weeks == 1:
        return True
    weeks_apart = (_monday(day) - _monday(pattern.anchor_date)).days // 7
    return weeks_apart % pattern.every_n_weeks == 0


def _blackout_days(start: date, end: date) -> set[date]:
    days = set()
    for period in BlackoutPeriod.objects.filter(start_date__lte=end, end_date__gte=start):
        day = max(period.start_date, start)
        while day <= min(period.end_date, end):
            days.add(day)
            day += timedelta(days=1)
    return days


def plan_fill(start: date, end: date, template_week=None) -> FillPlan:
    """Work out what filling this date range would create, without creating anything."""
    if end < start:
        raise ValueError("The end date is before the start date.")
    if (end - start).days > MAX_FILL_WEEKS * 7:
        raise ValueError(f"Fill at most {MAX_FILL_WEEKS} weeks at a time.")
    patterns = ShiftPattern.objects.filter(active_from__lte=end).filter(
        Q(active_until__isnull=True) | Q(active_until__gte=start)
    )
    if template_week is not None:
        patterns = patterns.filter(template_week=template_week)
    patterns = list(patterns.select_related("required_training", "teaches"))
    existing = set(
        Shift.objects.filter(pattern__in=patterns, local_date__range=(start, end)).values_list(
            "pattern_id", "local_date"
        )
    )
    blackouts = _blackout_days(start, end)
    holidays = holidays_between(start, end)

    plan = FillPlan(start=start, end=end)
    day = start
    while day <= end:
        for pattern in patterns:
            if not runs_on(pattern, day):
                continue
            if (pattern.pk, day) in existing:
                plan.already_there += 1
                continue
            planned = PlannedShift(pattern, day, holiday_label(holidays.get(day, [])))
            if day in blackouts:
                plan.blacked_out.append(planned)
            else:
                plan.new.append(planned)
        day += timedelta(days=1)
    return plan


@transaction.atomic
def apply_fill(plan: FillPlan, *, skip_days: set[date] = frozenset(), by=None) -> int:
    """Create the planned shifts, leaving out holiday days staff chose to skip."""
    shifts = []
    for planned in plan.new:
        if planned.day in skip_days:
            continue
        pattern = planned.pattern
        shifts.append(
            Shift(
                pattern=pattern,
                title=pattern.title,
                kind=pattern.kind,
                teaches=pattern.teaches,
                required_training=pattern.required_training,
                starts_at=planned.starts_at(),
                ends_at=planned.ends_at(),
                local_date=planned.day,
                capacity=pattern.capacity,
                needs_approval=pattern.needs_approval,
                notes=pattern.notes,
                holiday_name=planned.holiday,
                created_by=by,
            )
        )
    # ignore_conflicts: if two people fill at once, the second simply finds them there.
    created = Shift.objects.bulk_create(shifts, ignore_conflicts=True)
    audit.record(
        "schedule.filled",
        actor=by,
        target_repr=f"{plan.start} to {plan.end}",
        shifts=len(created),
        skipped_days=sorted(str(d) for d in skip_days),
    )
    return len(created)
