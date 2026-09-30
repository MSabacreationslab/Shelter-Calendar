"""Reports (SPEC §6, Phase 7): Sunday digest, monthly summary, report page and CSV."""

import csv
import io
from datetime import date, datetime, time, timedelta

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.utils import timezone

from core.models import ShelterSettings
from reports import csv_export, data, senders
from reports.models import SentReport
from scheduling.models import Signup, SignupStatus
from tests.factories import ShiftFactory, TrainingTypeFactory, UserFactory, trained

pytestmark = pytest.mark.django_db


def moment(day: date, hour: int) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour)))


def book(person, shift, **fields):
    return Signup.objects.create(
        shift=shift, volunteer=person, period=(shift.starts_at, shift.ends_at), **fields
    )


@pytest.fixture
def notify():
    ShelterSettings.load()
    ShelterSettings.objects.update(notify_emails="lead@example.com\nassistant@example.com")


@pytest.fixture
def next_week():
    return data.next_monday(timezone.localdate())


# Dates


def test_next_monday_from_a_sunday_is_tomorrow():
    assert data.next_monday(date(2026, 10, 4)) == date(2026, 10, 5)
    assert data.next_monday(date(2026, 10, 5)) == date(2026, 10, 12)


def test_month_helpers_handle_leap_years():
    assert data.month_bounds(date(2028, 2, 1)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert data.previous_month_start(date(2027, 1, 1)) == date(2026, 12, 1)


# Sunday digest


def test_week_ahead_groups_shifts_by_day_and_person(next_week):
    tuesday = next_week + timedelta(days=1)
    walk = ShiftFactory(title="Dog walking", starts_at=moment(tuesday, 9), capacity=3)
    mary = UserFactory(first_name="Mary")
    book(mary, walk)
    week = data.week_ahead(next_week)
    assert [len(shifts) for _, shifts in week.days] == [0, 1, 0, 0, 0, 0, 0]
    shift = week.days[1][1][0]
    assert shift.people == [mary] and shift.open == 2
    assert week.by_person == [(mary, [shift])]


def test_digest_goes_to_everyone_on_the_notify_list(notify, next_week):
    tuesday = next_week + timedelta(days=1)
    walk = ShiftFactory(title="Dog walking", starts_at=moment(tuesday, 9), capacity=2)
    book(UserFactory(first_name="Mary"), walk)
    gone = UserFactory(first_name="Joe")
    later = ShiftFactory(title="Cat care", starts_at=moment(tuesday, 13))
    book(
        gone,
        later,
        status=SignupStatus.CANCELLED,
        cancelled_by=gone,
        cancelled_at=timezone.now(),
        was_urgent=True,
    )
    result = senders.send_weekly_digest()
    assert result.sent == 2
    assert sorted(m.to[0] for m in mail.outbox) == ["assistant@example.com", "lead@example.com"]
    body = mail.outbox[0].body
    assert "Next week's volunteer schedule" in mail.outbox[0].subject
    assert "Dog walking: Mary Tester (1 open)" in body
    assert "Joe Tester: Cat care" in body and "(urgent)" in body
    assert "&nbsp;" not in body


def test_digest_is_sent_once_per_week_unless_asked_again(notify):
    assert senders.send_weekly_digest().sent == 2
    second = senders.send_weekly_digest()
    assert second.sent == 0 and second.reason == senders.ALREADY_SENT
    assert len(mail.outbox) == 2
    assert senders.send_weekly_digest(again=True).sent == 2
    assert SentReport.objects.count() == 1


def test_without_a_notify_list_nothing_is_sent_or_recorded():
    result = senders.send_weekly_digest()
    assert result.reason == senders.NO_RECIPIENTS
    assert not SentReport.objects.exists()


def test_digest_command_can_act_as_another_day(notify):
    out = io.StringIO()
    call_command("send_weekly_digest", "--date", "2026-10-04", stdout=out)
    assert out.getvalue().strip() == "Sent to 2."
    assert SentReport.objects.get().period_start == date(2026, 10, 5)
    with pytest.raises(CommandError):
        call_command("send_weekly_digest", "--date", "Sunday")


# Monthly summary


def test_monthly_summary_numbers(notify):
    month = date(2027, 12, 1)
    in_month = timezone.make_aware(datetime(2027, 12, 10, 12))
    full = ShiftFactory(starts_at=moment(date(2027, 12, 6), 9), capacity=2)
    half = ShiftFactory(starts_at=moment(date(2027, 12, 8), 9), capacity=2)
    for person in (UserFactory(), UserFactory()):
        book(person, full, created_at=in_month)
    book(UserFactory(), half, created_at=in_month)
    quitter = UserFactory()
    book(
        quitter,
        ShiftFactory(starts_at=moment(date(2027, 12, 9), 9)),
        status=SignupStatus.CANCELLED,
        cancelled_by=quitter,
        cancelled_at=in_month,
        was_urgent=True,
        is_late_cancel=True,
        created_at=in_month,
    )
    UserFactory(date_joined=in_month)
    trained(UserFactory(), TrainingTypeFactory(name="Dog walking"), completed_on=date(2027, 12, 3))

    summary = data.month_summary(month)
    assert summary.shifts == 3
    assert (summary.filled, summary.spots, summary.fill_percent) == (3, 7, 43)
    assert summary.signups == 4
    assert (summary.cancellations, summary.urgent, summary.late) == (1, 1, 1)
    assert summary.volunteers_added == 1
    assert summary.trainings == [("Dog walking", 1)]

    assert senders.send_monthly_summary(date(2028, 1, 1)).sent == 2
    assert mail.outbox[0].subject == "Volunteer summary for December 2027"
    assert "Spots filled: 3 of 7 (43%)" in mail.outbox[0].body
    assert senders.send_monthly_summary(date(2028, 1, 1)).reason == senders.ALREADY_SENT


# Report page and CSV


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def test_report_page_shows_people_days_and_shifts(staff_client):
    day = date(2026, 6, 10)
    shift = ShiftFactory(title="Dog walking", starts_at=moment(day, 9))
    book(UserFactory(first_name="Mary"), shift)
    html = staff_client.get("/reports/?start=2026-06-01&end=2026-06-30").content.decode()
    assert "Mary Tester" in html
    assert "Dog walking" in html
    assert ">2.0<" in html  # two hours done


def test_report_dates_are_checked(staff_client):
    backwards = staff_client.get("/reports/?start=2026-06-30&end=2026-06-01").content.decode()
    assert "on or after the start date" in backwards
    too_long = staff_client.get("/reports/?start=2024-01-01&end=2026-06-01").content.decode()
    assert "a year or less" in too_long


def test_report_defaults_to_this_month(staff_client):
    first = timezone.localdate().replace(day=1)
    assert f'value="{first.isoformat()}"' in staff_client.get("/reports/").content.decode()


def test_csv_is_excel_friendly_and_formula_safe(staff_client):
    shift = ShiftFactory(title="=HYPERLINK(evil)", starts_at=moment(date(2026, 6, 10), 9))
    book(UserFactory(first_name="+Plus"), shift)
    response = staff_client.get("/reports/shifts.csv?start=2026-06-01&end=2026-06-30")
    text = response.content.decode("utf-8")
    assert response["Content-Type"].startswith("text/csv")
    assert "volunteers-shifts-2026-06-01-to-2026-06-30.csv" in response["Content-Disposition"]
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][0] == "Date"
    assert rows[1][3] == "'=HYPERLINK(evil)"
    people = staff_client.get("/reports/people.csv?start=2026-06-01&end=2026-06-30")
    person_rows = list(csv.reader(io.StringIO(people.content.decode().lstrip("﻿"))))
    assert person_rows[1][0] == "'+Plus Tester"


def test_unknown_tables_are_not_found(staff_client):
    assert staff_client.get("/reports/secrets.csv").status_code == 404


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx"])
def test_formula_starts_are_neutralised(value):
    assert csv_export.safe(value) == "'" + value


def test_numbers_and_ordinary_text_pass_through():
    assert csv_export.safe(-3) == -3
    assert csv_export.safe("Mary") == "Mary"
