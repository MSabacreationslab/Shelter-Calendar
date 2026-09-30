"""Shift reminders and birthday emails (SPEC §6, Phase 8).

Reminders are email only for now (Q14). They all go through `deliver`, so text
messages can be added later in one place without touching the rules.

- Sunday evening: people with 4 or more shifts next week get one list of them all.
- Every evening: everyone else gets a reminder about tomorrow's shifts.
- Every morning: birthday emails (Feb 29 birthdays are sent on Feb 28 in other years).

Each reminder is claimed in SentReminder before sending, so running a command twice
(or two schedules overlapping) never sends the same reminder twice.
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction

from accounts.models import Status, User
from notifications import email
from notifications.models import ReminderKind, SentReminder
from scheduling.models import ShiftStatus, Signup, SignupStatus

WEEK_LIST_FROM = 4  # shifts in a week before someone gets the Sunday list instead


def deliver(person: User, template: str, context: dict):
    """Send one reminder. The only place that decides how (email today; texts could go here)."""
    return email.send(
        template, to=person.email, related_user=person, context={"person": person, **context}
    )


def _claim(kind: str, person: User, for_date: date) -> bool:
    """Record this reminder as sent. False if it already was."""
    with transaction.atomic():
        _, created = SentReminder.objects.get_or_create(kind=kind, user=person, for_date=for_date)
    return created


def _shifts_by_person(start: date, end: date) -> dict:
    """Confirmed shifts between two dates for people who want reminders, grouped by person."""
    grouped = defaultdict(list)
    signups = (
        Signup.objects.filter(
            status=SignupStatus.CONFIRMED,
            shift__status=ShiftStatus.SCHEDULED,
            shift__local_date__range=(start, end),
            volunteer__status=Status.ACTIVE,
            volunteer__profile__wants_reminders=True,
        )
        .select_related("shift", "volunteer")
        .order_by("shift__starts_at")
    )
    for signup in signups:
        grouped[signup.volunteer].append(signup.shift)
    return grouped


def send_week_lists(today: date) -> int:
    """On Sundays: one email listing next week's shifts to everyone with 4 or more."""
    monday = today + timedelta(days=7 - today.weekday())
    sent = 0
    for person, shifts in _shifts_by_person(monday, monday + timedelta(days=6)).items():
        if len(shifts) >= WEEK_LIST_FROM and _claim(ReminderKind.WEEK, person, monday):
            deliver(person, "reminder_week", {"shifts": shifts, "monday": monday})
            sent += 1
    return sent


def send_evening_reminders(today: date) -> int:
    """Each evening: a reminder about tomorrow, unless they already had this week's list."""
    tomorrow = today + timedelta(days=1)
    week_of = tomorrow - timedelta(days=tomorrow.weekday())
    had_list = set(
        SentReminder.objects.filter(kind=ReminderKind.WEEK, for_date=week_of).values_list(
            "user_id", flat=True
        )
    )
    sent = 0
    for person, shifts in _shifts_by_person(tomorrow, tomorrow).items():
        if person.pk in had_list:
            continue
        if _claim(ReminderKind.EVENING, person, tomorrow):
            deliver(person, "reminder_evening", {"shifts": shifts})
            sent += 1
    return sent


def send_reminders(today: date) -> tuple[int, int]:
    """The evening run: Sunday lists first (so those people are skipped), then tomorrow's."""
    lists = send_week_lists(today) if today.weekday() == calendar.SUNDAY else 0
    return lists, send_evening_reminders(today)


def birthday_days(today: date) -> list[tuple[int, int]]:
    """(month, day) pairs celebrated today: Feb 28 also covers Feb 29 outside leap years."""
    days = [(today.month, today.day)]
    if today.month == 2 and today.day == 28 and not calendar.isleap(today.year):
        days.append((2, 29))
    return days


def send_birthdays(today: date) -> int:
    """A thank-you on each person's birthday, if they gave one."""
    sent = 0
    for month, day in birthday_days(today):
        people = User.objects.filter(
            status=Status.ACTIVE, profile__birthday_month=month, profile__birthday_day=day
        ).exclude(email="")
        for person in people:
            if _claim(ReminderKind.BIRTHDAY, person, today):
                deliver(person, "birthday", {})
                sent += 1
    return sent
