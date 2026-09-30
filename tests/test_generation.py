"""Filling the schedule from patterns (SPEC §6, Phase 3)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from core.models import AuditEvent
from scheduling import generation
from scheduling.holidays import sync_federal_holidays
from scheduling.models import BlackoutPeriod, Holiday, HolidaySource, Shift
from tests.factories import PatternFactory

pytestmark = pytest.mark.django_db

OCT_1 = date(2026, 10, 1)  # a Thursday


def _fill(start, end, **kwargs):
    plan = generation.plan_fill(start, end)
    generation.apply_fill(plan, **kwargs)
    return plan


def test_weekly_pattern_makes_one_shift_each_matching_day():
    PatternFactory(weekday=3)
    _fill(OCT_1, OCT_1 + timedelta(days=27))
    days = list(Shift.objects.values_list("local_date", flat=True).order_by("local_date"))
    assert days == [OCT_1 + timedelta(weeks=n) for n in range(4)]
    assert all(d.weekday() == 3 for d in days)


def test_every_other_week_counts_from_its_start_week():
    PatternFactory(weekday=3, every_n_weeks=2, active_from=OCT_1)
    _fill(OCT_1, OCT_1 + timedelta(days=34))
    days = list(Shift.objects.values_list("local_date", flat=True).order_by("local_date"))
    assert days == [OCT_1, OCT_1 + timedelta(weeks=2), OCT_1 + timedelta(weeks=4)]


def test_nine_am_stays_nine_am_across_the_daylight_saving_change():
    # Clocks go back on Sunday, November 1, 2026.
    PatternFactory(weekday=3)
    _fill(date(2026, 10, 29), date(2026, 11, 5))
    before, after = Shift.objects.order_by("starts_at")
    assert timezone.localtime(before.starts_at).hour == 9
    assert timezone.localtime(after.starts_at).hour == 9
    # The extra hour is the clock change: 9:00 EDT to 9:00 EST.
    assert after.starts_at - before.starts_at == timedelta(days=7, hours=1)


def test_filling_twice_never_duplicates():
    PatternFactory()
    _fill(OCT_1, OCT_1 + timedelta(days=13))
    again = generation.plan_fill(OCT_1, OCT_1 + timedelta(days=13))
    assert again.new == []
    assert again.already_there == 2
    generation.apply_fill(again)
    assert Shift.objects.count() == 2


def test_closed_days_are_skipped():
    PatternFactory()
    BlackoutPeriod.objects.create(start_date=OCT_1, end_date=OCT_1, reason="Staff training")
    plan = _fill(OCT_1, OCT_1 + timedelta(days=7))
    assert [p.day for p in plan.blacked_out] == [OCT_1]
    assert list(Shift.objects.values_list("local_date", flat=True)) == [OCT_1 + timedelta(weeks=1)]


def test_holidays_are_flagged_and_can_be_skipped_day_by_day():
    PatternFactory(weekday=3)
    thanksgiving = date(2026, 11, 26)
    Holiday.objects.create(date=thanksgiving, name="Thanksgiving Day", source=HolidaySource.FEDERAL)
    plan = generation.plan_fill(date(2026, 11, 19), thanksgiving)
    assert plan.holiday_days() == [(thanksgiving, "Thanksgiving Day", 1)]
    generation.apply_fill(plan, skip_days={thanksgiving})
    assert list(Shift.objects.values_list("local_date", flat=True)) == [date(2026, 11, 19)]


def test_kept_holiday_shifts_carry_the_holiday_name():
    PatternFactory(weekday=3)
    Holiday.objects.create(
        date=date(2026, 11, 26), name="Thanksgiving Day", source=HolidaySource.FEDERAL
    )
    _fill(date(2026, 11, 26), date(2026, 11, 26))
    assert Shift.objects.get().holiday_name == "Thanksgiving Day"


def test_hidden_holidays_are_not_flagged():
    PatternFactory(weekday=3)
    Holiday.objects.create(
        date=date(2026, 10, 8), name="Hidden day", source=HolidaySource.FEDERAL, hidden=True
    )
    plan = generation.plan_fill(date(2026, 10, 8), date(2026, 10, 8))
    assert plan.holiday_days() == []


def test_patterns_only_run_between_their_start_and_end():
    PatternFactory(active_from=date(2026, 10, 8), active_until=date(2026, 10, 15))
    _fill(OCT_1, OCT_1 + timedelta(days=27))
    days = list(Shift.objects.values_list("local_date", flat=True).order_by("local_date"))
    assert days == [date(2026, 10, 8), date(2026, 10, 15)]


def test_shifts_copy_the_patterns_details():
    pattern = PatternFactory(title="Evening cats", capacity=4, notes="Meet at the side door")
    _fill(OCT_1, OCT_1)
    shift = Shift.objects.get()
    assert (shift.title, shift.capacity, shift.notes, shift.pattern) == (
        "Evening cats",
        4,
        "Meet at the side door",
        pattern,
    )


def test_fill_is_limited_to_twenty_six_weeks():
    with pytest.raises(ValueError):
        generation.plan_fill(OCT_1, OCT_1 + timedelta(weeks=27))


def test_fill_is_recorded_in_the_change_log():
    PatternFactory()
    _fill(OCT_1, OCT_1 + timedelta(days=6))
    event = AuditEvent.objects.get(action="schedule.filled")
    assert event.details["shifts"] == 1


def test_federal_holidays_sync_is_safe_to_repeat_and_keeps_hidden_ones_hidden():
    added = sync_federal_holidays([2026])
    assert added >= 11
    christmas = Holiday.objects.get(date=date(2026, 12, 25))
    christmas.hidden = True
    christmas.save()
    assert sync_federal_holidays([2026]) == 0
    christmas.refresh_from_db()
    assert christmas.hidden
