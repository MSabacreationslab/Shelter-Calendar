"""What a volunteer's calendar and lists show (SPEC §6, Phase 4)."""

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from core.templatetags.formatting import MONTHS
from scheduling.models import (
    Shift,
    ShiftStatus,
    Signup,
    SignupStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from training.eligibility import eligible_filter

# Sunday first, as on most American calendars.
WEEK_STARTS = calendar.SUNDAY
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
FIND_DAYS = 14


@dataclass
class CalendarDay:
    day: date
    in_month: bool
    is_today: bool
    mine: int
    open: int


def greeting(now=None) -> str:
    """Good morning / afternoon / evening, in shelter time."""
    hour = timezone.localtime(now or timezone.now()).hour
    if hour < 12:
        return "Good morning"
    return "Good afternoon" if hour < 17 else "Good evening"


def month_start(value: str | None) -> date:
    """The first of the month from "2026-10", or this month if it's missing or wrong."""
    today = timezone.localdate()
    try:
        year, month = (int(part) for part in (value or "").split("-"))
        return date(year, month, 1)
    except ValueError:
        return today.replace(day=1)


def shift_month(first: date, months: int) -> date:
    """The first of the month `months` away."""
    index = first.year * 12 + first.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month_label(first: date) -> str:
    """October 2026."""
    return f"{MONTHS[first.month - 1]} {first.year}"


def my_signups(user):
    """This person's upcoming shifts, soonest first."""
    return (
        Signup.objects.filter(
            volunteer=user,
            status=SignupStatus.CONFIRMED,
            shift__status=ShiftStatus.SCHEDULED,
            shift__ends_at__gt=timezone.now(),
        )
        .select_related("shift")
        .order_by("shift__starts_at")
    )


def open_shifts(user, start: date, end: date):
    """Shifts this person could take between two dates that still have space."""
    mine = Signup.objects.filter(volunteer=user, status=SignupStatus.CONFIRMED).values("shift_id")
    return (
        Shift.objects.filter(eligible_filter(user), local_date__range=(start, end))
        .annotate(filled=Count("signups", filter=Q(signups__status=SignupStatus.CONFIRMED)))
        .annotate(spots=F("capacity") - F("filled"))
        .filter(filled__lt=F("capacity"))
        .exclude(pk__in=mine)
        .select_related("required_training", "teaches")
        .order_by("starts_at")
    )


def month_grid(user, first: date) -> list[list[CalendarDay]]:
    """Weeks of days for the month, each marked with the person's shifts and open shifts."""
    weeks = calendar.Calendar(firstweekday=WEEK_STARTS).monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1]
    today = timezone.localdate()
    mine = Counter(
        my_signups(user)
        .filter(shift__local_date__range=(start, end))
        .values_list("shift__local_date", flat=True)
    )
    available = Counter(
        s.local_date
        for s in open_shifts(user, max(start, today), end)
        if s.starts_at > timezone.now()
    )
    return [
        [
            CalendarDay(
                day=day,
                in_month=day.month == first.month,
                is_today=day == today,
                mine=mine[day],
                open=available[day],
            )
            for day in week
        ]
        for week in weeks
    ]


def day_shifts(user, day: date):
    """Everything on one day, for the day page: what I'm on, and what I could do."""
    mine = list(my_signups(user).filter(shift__local_date=day))
    mine_ids = {s.shift_id for s in mine}
    waiting = set(
        WaitlistEntry.objects.filter(
            volunteer=user, status=WaitlistStatus.WAITING, shift__local_date=day
        ).values_list("shift_id", flat=True)
    )
    others = (
        Shift.objects.filter(eligible_filter(user), local_date=day)
        .exclude(pk__in=mine_ids)
        .annotate(
            # distinct: two joins in one query would otherwise multiply each other's counts.
            filled=Count(
                "signups", filter=Q(signups__status=SignupStatus.CONFIRMED), distinct=True
            ),
            waiting_count=Count(
                "waitlist", filter=Q(waitlist__status=WaitlistStatus.WAITING), distinct=True
            ),
        )
        .annotate(spots=F("capacity") - F("filled"))
        .select_related("required_training", "teaches")
        .order_by("starts_at")
    )
    return mine, list(others), waiting


def find_list(user, days: int = FIND_DAYS):
    """Open shifts for the next two weeks, grouped by day."""
    today = timezone.localdate()
    grouped: dict[date, list] = {}
    for shift in open_shifts(user, today, today + timedelta(days=days)):
        if shift.starts_at > timezone.now():
            grouped.setdefault(shift.local_date, []).append(shift)
    return sorted(grouped.items())


def ics(shift, shelter_name: str) -> str:
    """A calendar file for one shift, for "Add to my calendar"."""

    def stamp(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    def escape(text: str) -> str:
        return (
            text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Shelter volunteer schedule//EN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:shift-{shift.pk}@shelter-volunteers",
        f"DTSTAMP:{stamp(timezone.now())}",
        f"DTSTART:{stamp(shift.starts_at)}",
        f"DTEND:{stamp(shift.ends_at)}",
        f"SUMMARY:{escape(shift.title)} ({escape(shelter_name)})",
        f"LOCATION:{escape(shelter_name)}",
    ]
    if shift.notes:
        lines.append(f"DESCRIPTION:{escape(shift.notes)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
