"""US federal holidays plus the shelter's own. Holidays are flags only (SPEC Q10)."""

from collections import defaultdict
from datetime import date

import holidays as holiday_calendar
from django.db import transaction
from django.utils import timezone

from core import audit
from scheduling.models import Holiday, HolidaySource


def sync_federal_holidays(years=None) -> int:
    """Add this year's and next year's federal holidays. Safe to run any number of times."""
    this_year = timezone.localdate().year
    years = years or [this_year, this_year + 1]
    added = 0
    for day, name in holiday_calendar.country_holidays("US", years=years).items():
        _, created = Holiday.objects.get_or_create(
            date=day, name=name, defaults={"source": HolidaySource.FEDERAL}
        )
        added += created
    return added


def holidays_between(start: date, end: date) -> dict[date, list[str]]:
    """Names of the flagged (not hidden) holidays on each day in the range."""
    by_day = defaultdict(list)
    for holiday in Holiday.objects.filter(date__range=(start, end), hidden=False):
        by_day[holiday.date].append(holiday.name)
    return dict(by_day)


def holiday_label(names: list[str]) -> str:
    """One label for a day, even when two holidays share it."""
    return " / ".join(names)


@transaction.atomic
def add_shelter_holiday(day: date, name: str, *, by) -> Holiday:
    """A day the shelter treats as a holiday (it's flagged; closures are blackouts)."""
    holiday = Holiday.objects.create(date=day, name=name, source=HolidaySource.SHELTER)
    audit.record("holiday.added", actor=by, target_repr=f"{name} ({day})")
    return holiday


@transaction.atomic
def set_hidden(holiday: Holiday, hidden: bool, *, by) -> None:
    """Hide a holiday the shelter doesn't observe, or show it again."""
    holiday.hidden = hidden
    holiday.save(update_fields=["hidden"])
    audit.record(
        "holiday.hidden" if hidden else "holiday.shown",
        actor=by,
        target_repr=f"{holiday.name} ({holiday.date})",
    )


@transaction.atomic
def remove_shelter_holiday(holiday: Holiday, *, by) -> None:
    """Shelter holidays can be removed; federal ones can only be hidden."""
    if holiday.source != HolidaySource.SHELTER:
        raise ValueError("Federal holidays can be hidden, not removed.")
    audit.record("holiday.removed", actor=by, target_repr=f"{holiday.name} ({holiday.date})")
    holiday.delete()
