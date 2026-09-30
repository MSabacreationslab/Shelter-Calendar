"""Staff schedule screens: they call the services and show their answers in plain words."""

from datetime import date, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from scheduling import services as booking
from scheduling.models import (
    BlackoutPeriod,
    Holiday,
    HolidaySource,
    Shift,
    ShiftPattern,
    ShiftStatus,
    Signup,
    SignupStatus,
    TemplateWeek,
)
from tests.factories import PatternFactory, ShiftFactory, UserFactory, at

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def ready(**kwargs):
    return UserFactory(profile__no_training_eligible=True, **kwargs)


def next_weekday(weekday):
    today = timezone.localdate()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def test_week_view_shows_shifts_holidays_and_closed_days(staff_client):
    day = next_weekday(3)
    shift = ShiftFactory(title="Evening cats", starts_at=at((day - timezone.localdate()).days, 17))
    Holiday.objects.create(date=day, name="Founders Day", source=HolidaySource.SHELTER)
    BlackoutPeriod.objects.create(start_date=day, end_date=day, reason="Inspection")
    html = staff_client.get(f"/schedule/?week={day.isoformat()}").content.decode()
    assert "Evening cats" in html
    assert "0 of 3 filled" in html
    assert "Holiday: Founders Day" in html
    assert "Closed day" in html
    assert f"/schedule/shifts/{shift.pk}/" in html


def test_fill_previews_first_then_creates_skipping_chosen_holidays(staff_client):
    start = next_weekday(3)
    PatternFactory(weekday=3, active_from=start)
    holiday = start + timedelta(weeks=1)
    Holiday.objects.create(date=holiday, name="Founders Day", source=HolidaySource.SHELTER)
    end = start + timedelta(weeks=2)
    preview = staff_client.post(
        "/schedule/fill/", {"start": start.isoformat(), "end": end.isoformat(), "step": "preview"}
    )
    assert "Skip Founders Day" in preview.content.decode()
    assert not Shift.objects.exists()
    staff_client.post(
        "/schedule/fill/",
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": "confirm",
            "skip": [holiday.isoformat()],
        },
    )
    assert sorted(Shift.objects.values_list("local_date", flat=True)) == [start, end]


def test_one_off_and_repeating_shifts(staff_client):
    day = next_weekday(1)
    base = {
        "title": "Adoption event",
        "day": day.isoformat(),
        "start_time": "10:00",
        "end_time": "14:00",
        "capacity": "5",
        "kind": "regular",
    }
    staff_client.post("/schedule/add/", base)
    assert Shift.objects.filter(title="Adoption event").count() == 1
    repeat = {**base, "title": "Laundry", "repeat_until": (day + timedelta(weeks=3)).isoformat()}
    staff_client.post("/schedule/add/", repeat)
    assert Shift.objects.filter(title="Laundry").count() == 4
    assert ShiftPattern.objects.filter(title="Laundry", template_week=None).exists()


def test_past_dates_and_backwards_times_are_explained(staff_client):
    html = staff_client.post(
        "/schedule/add/",
        {
            "title": "Oops",
            "day": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "start_time": "14:00",
            "end_time": "10:00",
            "capacity": "1",
            "kind": "regular",
        },
    ).content.decode()
    assert "Please choose today or a later date." in html
    assert "The end time needs to be after the start time." in html


def test_staff_add_and_remove_people_on_a_shift(staff_client):
    shift = ShiftFactory()
    person = ready(first_name="Mary")
    staff_client.post(f"/schedule/shifts/{shift.pk}/assign/", {"person": person.pk})
    signup = Signup.objects.get(shift=shift, volunteer=person)
    confirm = staff_client.get(f"/schedule/shifts/{shift.pk}/remove/{signup.pk}/")
    assert "Take Mary" in confirm.content.decode()
    staff_client.post(f"/schedule/shifts/{shift.pk}/remove/{signup.pk}/")
    signup.refresh_from_db()
    assert signup.status == SignupStatus.CANCELLED


def test_assigning_someone_without_the_training_explains_why(staff_client):
    shift = ShiftFactory()
    person = UserFactory(first_name="Newbie")
    response = staff_client.post(
        f"/schedule/shifts/{shift.pk}/assign/", {"person": person.pk}, follow=True
    )
    assert "can&#x27;t take shifts yet" in response.content.decode()


def test_promoting_from_the_waitlist_screen(staff_client, django_capture_on_commit_callbacks):
    shift = ShiftFactory(capacity=1)
    first = ready()
    signup = booking.sign_up(first, shift).signup
    waiting = ready()
    entry = booking.join_waitlist(waiting, shift).entry
    booking.cancel_signup(signup, by=first)
    with django_capture_on_commit_callbacks(execute=True):
        staff_client.post(f"/schedule/shifts/{shift.pk}/waitlist/{entry.pk}/promote/")
    assert Signup.objects.filter(shift=shift, volunteer=waiting, status="confirmed").exists()
    assert mail.outbox[-1].to == [waiting.email]


def test_shrinking_a_shift_on_screen_names_who_is_in_the_way(staff_client):
    shift = ShiftFactory(capacity=2)
    booking.sign_up(ready(first_name="Mary"), shift)
    booking.sign_up(ready(first_name="Joe"), shift)
    response = staff_client.post(
        f"/schedule/shifts/{shift.pk}/edit/",
        {"title": shift.title, "start_time": "09:00", "end_time": "11:00", "capacity": "1"},
    )
    html = response.content.decode()
    assert "Mary" in html and "Joe" in html
    shift.refresh_from_db()
    assert shift.capacity == 2


def test_cancelling_a_shift_on_screen(staff_client, django_capture_on_commit_callbacks):
    shift = ShiftFactory()
    person = ready()
    booking.sign_up(person, shift)
    with django_capture_on_commit_callbacks(execute=True):
        staff_client.post(f"/schedule/shifts/{shift.pk}/cancel/", {"reason": "Water leak"})
    shift.refresh_from_db()
    assert shift.status == ShiftStatus.CANCELLED
    assert "Water leak" in mail.outbox[-1].body


def test_template_week_patterns_and_their_future_shifts(staff_client):
    staff_client.post("/schedule/templates/", {"name": "Regular week"})
    week = TemplateWeek.objects.get(name="Regular week")
    start = next_weekday(3)
    staff_client.post(
        f"/schedule/templates/{week.pk}/add/",
        {
            "title": "Dog walking",
            "weekday": "3",
            "start_time": "09:00",
            "end_time": "11:00",
            "every_n_weeks": "1",
            "active_from": start.isoformat(),
            "capacity": "2",
            "kind": "regular",
        },
    )
    pattern = ShiftPattern.objects.get(title="Dog walking")
    staff_client.post(
        "/schedule/fill/",
        {
            "start": start.isoformat(),
            "end": (start + timedelta(weeks=1)).isoformat(),
            "step": "confirm",
        },
    )
    booked, untouched = Shift.objects.filter(pattern=pattern).order_by("starts_at")
    booking.sign_up(ready(), booked)
    response = staff_client.post(
        f"/schedule/patterns/{pattern.pk}/",
        {
            "title": "Dog walking",
            "start_time": "10:00",
            "end_time": "12:00",
            "capacity": "3",
            "kind": "regular",
        },
    )
    untouched.refresh_from_db()
    booked.refresh_from_db()
    assert timezone.localtime(untouched.starts_at).hour == 10 and untouched.capacity == 3
    assert timezone.localtime(booked.starts_at).hour == 9
    assert "kept the old details" in response.content.decode()


def test_stopping_a_pattern_removes_its_empty_future_shifts(staff_client):
    start = next_weekday(3)
    pattern = PatternFactory(weekday=3, active_from=start)
    staff_client.post(
        "/schedule/fill/",
        {
            "start": start.isoformat(),
            "end": (start + timedelta(weeks=2)).isoformat(),
            "step": "confirm",
        },
    )
    staff_client.post(f"/schedule/patterns/{pattern.pk}/stop/", {"last_day": start.isoformat()})
    assert list(Shift.objects.values_list("local_date", flat=True)) == [start]


def test_closed_days_list_shifts_already_on_them(staff_client):
    day = next_weekday(2)
    ShiftFactory(title="Cat enrichment", starts_at=at((day - timezone.localdate()).days, 10))
    html = staff_client.post(
        "/schedule/closed-days/",
        {"start_date": day.isoformat(), "end_date": day.isoformat(), "reason": "Inspection"},
    ).content.decode()
    assert "already fall on those days" in html
    assert Shift.objects.get().status == ShiftStatus.SCHEDULED


def test_holidays_can_be_added_hidden_and_removed(staff_client):
    day = date(timezone.localdate().year + 1, 3, 3)
    staff_client.post("/schedule/holidays/", {"day": day.isoformat(), "name": "Founders Day"})
    holiday = Holiday.objects.get(name="Founders Day")
    staff_client.post(f"/schedule/holidays/{holiday.pk}/toggle/")
    holiday.refresh_from_db()
    assert holiday.hidden
    staff_client.post(f"/schedule/holidays/{holiday.pk}/remove/")
    assert not Holiday.objects.filter(name="Founders Day").exists()


def test_federal_holidays_cannot_be_removed(staff_client):
    federal = Holiday.objects.create(
        date=date(2027, 7, 4), name="Independence Day", source=HolidaySource.FEDERAL
    )
    assert staff_client.post(f"/schedule/holidays/{federal.pk}/remove/").status_code == 404


def test_volunteers_see_no_schedule_tools(client, volunteer):
    client.force_login(volunteer)
    assert client.get("/schedule/").status_code == 403
