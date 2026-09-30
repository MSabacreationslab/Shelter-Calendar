from datetime import UTC, datetime, time, timedelta

import pytest
from django.utils import timezone

from core.phones import format_phone, normalize_phone
from core.templatetags.formatting import clock, friendly_date, long_date, month_name


@pytest.mark.parametrize(
    "typed", ["(740) 555-0142", "740.555.0142", "7405550142", "+1 740 555 0142", "1-740-555-0142"]
)
def test_phone_numbers_normalize_to_ten_digits(typed):
    assert normalize_phone(typed) == "7405550142"


@pytest.mark.parametrize("typed", ["555-0142", "", "2-740-555-0142", "740555014299"])
def test_bad_phone_numbers_are_refused(typed):
    with pytest.raises(ValueError):
        normalize_phone(typed)


def test_phone_display():
    assert format_phone("7405550142") == "(740) 555-0142"
    assert format_phone("") == ""


def test_dates_always_include_the_weekday():
    assert long_date(datetime(2026, 10, 6).date()) == "Tuesday, October 6"


def test_times_are_twelve_hour_and_never_split():
    assert clock(time(9, 0)) == "9:00&nbsp;AM"
    assert clock(time(12, 30)) == "12:30&nbsp;PM"
    assert clock(time(0, 5)) == "12:05&nbsp;AM"


def test_aware_times_show_in_shelter_time():
    utc_moment = datetime(2026, 10, 6, 13, 0, tzinfo=UTC)
    assert clock(utc_moment) == "9:00&nbsp;AM"


def test_month_names():
    assert month_name(3) == "March"
    assert month_name("") == ""


def test_friendly_dates_say_today_and_tomorrow():
    today = timezone.localdate()
    assert friendly_date(today).startswith("Today, ")
    assert friendly_date(today + timedelta(days=1)).startswith("Tomorrow, ")
    assert friendly_date(today + timedelta(days=2)) == long_date(today + timedelta(days=2))
