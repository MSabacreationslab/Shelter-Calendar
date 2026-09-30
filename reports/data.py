"""The numbers and lists behind the digest, the monthly summary and the report page.

One place computes them, so an email and the report page never disagree.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from accounts.models import Role, User
from scheduling.models import Shift, ShiftStatus, Signup, SignupStatus
from training.models import TrainingRecord

MAX_REPORT_DAYS = 366


def next_monday(today: date) -> date:
    """The Monday after today (run on a Sunday, that's tomorrow)."""
    return today + timedelta(days=7 - today.weekday())


def month_bounds(first: date) -> tuple[date, date]:
    """First and last day of the month that starts on `first`."""
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, following - timedelta(days=1)


def previous_month_start(today: date) -> date:
    """The 1st of last month (run on the 1st, that's the month just finished)."""
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def _shifts_between(start: date, end: date):
    return (
        Shift.objects.filter(local_date__range=(start, end))
        .annotate(
            filled=Count("signups", filter=Q(signups__status=SignupStatus.CONFIRMED), distinct=True)
        )
        .order_by("starts_at", "title")
    )


def _people_on(shifts) -> dict[int, list[User]]:
    people = defaultdict(list)
    for signup in (
        Signup.objects.filter(shift__in=shifts, status=SignupStatus.CONFIRMED)
        .select_related("volunteer")
        .order_by("volunteer__first_name", "volunteer__last_name")
    ):
        people[signup.shift_id].append(signup.volunteer)
    return people


@dataclass
class WeekAhead:
    start: date
    end: date
    days: list = field(default_factory=list)  # [(date, [shift…])], each shift with .people, .open
    by_person: list = field(default_factory=list)  # [(person, [shift…])]


def week_ahead(start: date) -> WeekAhead:
    """Monday to Sunday: each day's shifts with names and open spots, and each person's shifts."""
    end = start + timedelta(days=6)
    shifts = list(_shifts_between(start, end).filter(status=ShiftStatus.SCHEDULED))
    people = _people_on(shifts)
    week = WeekAhead(start=start, end=end)
    by_person = defaultdict(list)
    for offset in range(7):
        day = start + timedelta(days=offset)
        todays = []
        for shift in (s for s in shifts if s.local_date == day):
            shift.people = people.get(shift.pk, [])
            shift.open = max(shift.capacity - shift.filled, 0)
            todays.append(shift)
            for person in shift.people:
                by_person[person].append(shift)
        week.days.append((day, todays))
    week.by_person = sorted(by_person.items(), key=lambda item: item[0].get_full_name())
    return week


def cancellations_between(start, end):
    """Volunteers' own cancellations made between two moments, urgent first."""
    return list(
        Signup.objects.filter(
            status=SignupStatus.CANCELLED,
            cancelled_at__gte=start,
            cancelled_at__lt=end,
            cancelled_by=F("volunteer"),
        )
        .select_related("shift", "volunteer")
        .order_by("-was_urgent", "cancelled_at")
    )


@dataclass
class MonthSummary:
    start: date
    end: date
    shifts: int
    spots: int
    filled: int
    signups: int
    cancellations: int
    urgent: int
    late: int
    volunteers_added: int
    trainings: list  # [(training name, count)]

    @property
    def fill_percent(self) -> int:
        """Share of spots filled, as a whole number."""
        return round(100 * self.filled / self.spots) if self.spots else 0

    @property
    def trainings_total(self) -> int:
        """All trainings completed in the month."""
        return sum(count for _, count in self.trainings)


def month_summary(first: date) -> MonthSummary:
    """The month in numbers: shifts, how full they were, sign-ups, cancellations, training."""
    start, end = month_bounds(first)
    shifts = list(_shifts_between(start, end).filter(status=ShiftStatus.SCHEDULED))
    window = (_start_of(start), _start_of(end + timedelta(days=1)))
    cancelled = cancellations_between(*window)
    trainings = Counter(
        TrainingRecord.objects.filter(
            completed_on__range=(start, end), voided_at__isnull=True
        ).values_list("training_type__name", flat=True)
    )
    return MonthSummary(
        start=start,
        end=end,
        shifts=len(shifts),
        spots=sum(s.capacity for s in shifts),
        filled=sum(min(s.filled, s.capacity) for s in shifts),
        signups=Signup.objects.filter(created_at__gte=window[0], created_at__lt=window[1]).count(),
        cancellations=len(cancelled),
        urgent=sum(1 for c in cancelled if c.was_urgent),
        late=sum(1 for c in cancelled if c.is_late_cancel),
        volunteers_added=User.objects.filter(
            role=Role.VOLUNTEER, date_joined__gte=window[0], date_joined__lt=window[1]
        ).count(),
        trainings=sorted(trainings.items()),
    )


def _start_of(day: date) -> datetime:
    """Midnight at the start of a day, shelter time."""
    return timezone.make_aware(datetime.combine(day, time.min))


def _hours(shift) -> float:
    return (shift.ends_at - shift.starts_at).total_seconds() / 3600


@dataclass
class RangeReport:
    start: date
    end: date
    by_person: list  # dicts: person, done, hours, coming_up, cancelled, urgent
    by_day: list  # dicts: day, shifts, spots, filled
    by_shift: list  # shifts with .people


def range_report(start: date, end: date, now=None) -> RangeReport:
    """Tables for the report page and its CSV downloads."""
    now = now or timezone.now()
    shifts = list(
        _shifts_between(start, end)
        .filter(status=ShiftStatus.SCHEDULED)
        .select_related("required_training", "teaches")
    )
    people = _people_on(shifts)
    per_person = defaultdict(
        lambda: {"done": 0, "hours": 0.0, "coming_up": 0, "cancelled": 0, "urgent": 0}
    )
    for shift in shifts:
        shift.people = people.get(shift.pk, [])
        for person in shift.people:
            row = per_person[person]
            if shift.ends_at <= now:
                row["done"] += 1
                row["hours"] += _hours(shift)
            else:
                row["coming_up"] += 1
    for signup in Signup.objects.filter(
        shift__local_date__range=(start, end),
        status=SignupStatus.CANCELLED,
        cancelled_by=F("volunteer"),
    ).select_related("volunteer"):
        per_person[signup.volunteer]["cancelled"] += 1
        per_person[signup.volunteer]["urgent"] += signup.was_urgent
    by_person = [
        {"person": person, **values, "hours": round(values["hours"], 1)}
        for person, values in sorted(per_person.items(), key=lambda item: item[0].get_full_name())
    ]
    by_day = []
    day = start
    while day <= end:
        todays = [s for s in shifts if s.local_date == day]
        if todays:
            by_day.append(
                {
                    "day": day,
                    "shifts": len(todays),
                    "spots": sum(s.capacity for s in todays),
                    "filled": sum(min(s.filled, s.capacity) for s in todays),
                }
            )
        day += timedelta(days=1)
    return RangeReport(start=start, end=end, by_person=by_person, by_day=by_day, by_shift=shifts)
