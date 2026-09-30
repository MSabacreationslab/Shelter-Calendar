"""Volunteer screens (SPEC §6, Phase 4): a volunteer can find, sign up for and cancel a shift."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from core.models import AuditEvent, ShelterSettings
from scheduling import services as booking
from scheduling.models import Signup, SignupStatus, WaitlistEntry, WaitlistStatus
from tests.factories import ShiftFactory, StaffFactory, TrainingTypeFactory, UserFactory, at

pytestmark = pytest.mark.django_db


@pytest.fixture
def person(client):
    """A signed-in volunteer who can take shifts that need no training."""
    volunteer = UserFactory(first_name="Mary", profile__no_training_eligible=True)
    client.force_login(volunteer)
    return volunteer


@pytest.fixture
def sent(django_capture_on_commit_callbacks):
    ShelterSettings.load()
    ShelterSettings.objects.update(notify_emails="lead@example.com")
    return lambda: django_capture_on_commit_callbacks(execute=True)


def _day(offset):
    return timezone.localdate() + timedelta(days=offset)


def test_volunteers_land_on_their_calendar(client, person):
    shift = ShiftFactory(title="Cat enrichment", starts_at=at(3, 10))
    booking.sign_up(person, shift)
    html = client.get("/").content.decode()
    assert "Mary" in html and "Your next shift" in html
    assert "Cat enrichment" in html
    month = _day(3).strftime("%Y-%m")
    calendar = client.get(f"/my-shifts/?month={month}").content.decode()
    assert f'href="/my-shifts/{_day(3).isoformat()}/"' in calendar


def test_calendar_marks_my_days_and_open_days(client, person):
    mine = ShiftFactory(starts_at=at(3, 10))
    booking.sign_up(person, mine)
    ShiftFactory(starts_at=at(4, 10))
    ShiftFactory(starts_at=at(4, 13))
    month = _day(3).strftime("%Y-%m")
    html = client.get(f"/my-shifts/?month={month}").content.decode()
    if _day(4).month == _day(3).month:
        assert "2 open shifts" in html
    assert ": your shift" in html
    assert "is-mine" in html


def test_month_buttons_say_the_month_name(client, person):
    html = client.get("/my-shifts/?month=2026-12").content.decode()
    assert "December 2026" in html
    assert 'href="?month=2026-11"><span aria-hidden="true">&#9664;</span> Nov' in html
    assert 'Nov<span class="calendar-head__rest">ember</span>' in html
    assert 'href="?month=2027-01">Jan<span class="calendar-head__rest">uary</span>' in html
    this_month = timezone.localdate().strftime("%Y-%m")
    assert f'href="?month={this_month}">Today</a>' in html


def test_day_page_lists_my_shifts_and_open_ones(client, person):
    mine = ShiftFactory(title="Laundry", starts_at=at(2, 9))
    booking.sign_up(person, mine)
    open_one = ShiftFactory(title="Dog walking", starts_at=at(2, 13), capacity=3)
    full = ShiftFactory(title="Cat cages", starts_at=at(2, 15), capacity=1)
    booking.sign_up(UserFactory(profile__no_training_eligible=True), full)
    html = client.get(f"/my-shifts/{_day(2).isoformat()}/").content.decode()
    assert "Laundry" in html and f"/shifts/{mine.pk}/cancel/" in html
    assert "3 spots left" in html and f"/shifts/{open_one.pk}/sign-up/" in html
    assert "Full" in html


def test_find_lists_only_shifts_i_can_take(client, person):
    ShiftFactory(title="Anyone can do this", starts_at=at(2, 9))
    ShiftFactory(
        title="Needs training", starts_at=at(2, 11), required_training=TrainingTypeFactory()
    )
    ShiftFactory(title="Too far away", starts_at=at(20, 9))
    html = client.get("/shifts/").content.decode()
    assert "Anyone can do this" in html
    assert "Needs training" not in html
    assert "Too far away" not in html


def test_signing_up_takes_two_steps(client, person):
    shift = ShiftFactory(title="Dog walking", starts_at=at(2, 9))
    confirm = client.get(f"/shifts/{shift.pk}/sign-up/")
    assert "Yes, sign me up" in confirm.content.decode()
    assert not Signup.objects.exists()
    response = client.post(f"/shifts/{shift.pk}/sign-up/")
    assert response["Location"] == f"/shifts/{shift.pk}/signed-up/"
    done = client.get(response["Location"]).content.decode()
    assert "You're signed up!" in done
    assert f"/shifts/{shift.pk}/calendar.ics" in done


def test_add_to_calendar_file(client, person):
    shift = ShiftFactory(title="Dog walking", starts_at=at(2, 9), notes="Side door, please")
    booking.sign_up(person, shift)
    response = client.get(f"/shifts/{shift.pk}/calendar.ics")
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in body and "SUMMARY:Dog walking" in body
    assert "DESCRIPTION:Side door\\, please" in body
    assert "\r\n" in body


def test_calendar_file_is_only_for_my_shifts(client, person):
    shift = ShiftFactory()
    assert client.get(f"/shifts/{shift.pk}/calendar.ics").status_code == 404


def test_a_full_shift_explains_itself(client, person):
    shift = ShiftFactory(capacity=1)
    booking.sign_up(UserFactory(profile__no_training_eligible=True), shift)
    response = client.post(f"/shifts/{shift.pk}/sign-up/", follow=True)
    assert "This shift is full." in response.content.decode()


def test_cancelling_early_is_simple(client, person, sent):
    shift = ShiftFactory(starts_at=at(5, 9))
    booking.sign_up(person, shift)
    page = client.get(f"/shifts/{shift.pk}/cancel/").content.decode()
    assert "Cancel this shift?" in page
    with sent():
        response = client.post(f"/shifts/{shift.pk}/cancel/", follow=True)
    assert "no longer signed up" in response.content.decode()
    assert Signup.objects.get(shift=shift).status == SignupStatus.CANCELLED
    assert mail.outbox == []


def test_cancelling_late_tells_the_team(client, person, sent):
    shift = ShiftFactory(starts_at=timezone.now() + timedelta(hours=6))
    booking.sign_up(person, shift)
    page = client.get(f"/shifts/{shift.pk}/cancel/").content.decode()
    assert "Can't make it?" in page or "Can&#x27;t make it?" in page
    with sent():
        response = client.post(
            f"/shifts/{shift.pk}/cancel/", {"reason": "Feeling unwell"}, follow=True
        )
    assert "told the volunteer team" in response.content.decode()
    assert Signup.objects.get(shift=shift).is_late_cancel
    assert "Feeling unwell" in mail.outbox[0].body


def test_after_the_start_you_are_asked_to_call(client, person):
    start = timezone.now() - timedelta(hours=1)
    shift = ShiftFactory(starts_at=start, ends_at=start + timedelta(hours=2))
    # Created directly: the booking rules rightly refuse a shift that has started.
    Signup.objects.create(shift=shift, volunteer=person, period=(shift.starts_at, shift.ends_at))
    html = client.get(f"/shifts/{shift.pk}/cancel/").content.decode()
    assert "already started" in html


def test_nobody_can_cancel_someone_elses_shift(client, person):
    other = UserFactory(profile__no_training_eligible=True)
    shift = ShiftFactory(starts_at=at(5, 9))
    booking.sign_up(other, shift)
    client.post(f"/shifts/{shift.pk}/cancel/")
    assert Signup.objects.get(volunteer=other).status == SignupStatus.CONFIRMED


def test_waitlist_from_the_shift_page(client, person):
    shift = ShiftFactory(capacity=1, starts_at=at(3, 9))
    booking.sign_up(UserFactory(profile__no_training_eligible=True), shift)
    page = client.get(f"/shifts/{shift.pk}/").content.decode()
    assert "Join the waitlist" in page
    client.post(f"/shifts/{shift.pk}/waitlist/")
    assert WaitlistEntry.objects.get(volunteer=person).status == WaitlistStatus.WAITING
    assert "on the waitlist" in client.get(f"/shifts/{shift.pk}/").content.decode()
    client.post(f"/shifts/{shift.pk}/leave-waitlist/")
    assert WaitlistEntry.objects.get(volunteer=person).status == WaitlistStatus.LEFT


def test_shift_page_explains_missing_training(client, person):
    shift = ShiftFactory(required_training=TrainingTypeFactory(name="Dog walking"))
    html = client.get(f"/shifts/{shift.pk}/").content.decode()
    assert "You need Dog walking training" in html
    assert "Sign up for this shift" not in html


def test_profile_changes_only_phone_and_emergency_contact(client, person):
    response = client.post(
        "/profile/",
        {
            "phone": "740 555 0199",
            "emergency_contact_name": "John",
            "emergency_contact_phone": "7405550111",
            "emergency_contact_relationship": "Brother",
            "first_name": "Hacked",
            "email": "evil@example.com",
            "role": "admin",
        },
    )
    assert response["Location"] == "/profile/"
    person.refresh_from_db()
    assert person.phone == "7405550199"
    assert person.profile.emergency_contact_name == "John"
    assert (person.first_name, person.email, person.role) == (
        "Mary",
        "mary@example.com",
        "volunteer",
    )
    event = AuditEvent.objects.get(action="profile.updated", target_user=person)
    assert "phone" in event.details["fields"]


def test_staff_have_my_shifts_too(client):
    staff = StaffFactory()
    client.force_login(staff)
    assert "<h1>Dashboard</h1>" in client.get("/").content.decode()
    assert client.get("/my-shifts/").status_code == 200
    assert 'href="/my-shifts/"' in client.get("/").content.decode()
