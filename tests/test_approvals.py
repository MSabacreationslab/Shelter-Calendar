"""Shift approvals (SPEC §6, Phase 9): approval shifts, people who need approval, and the
staff screen that answers them."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from accounts import people
from core.models import AuditEvent, ShelterSettings
from notifications.email import send
from notifications.models import EmailLog
from scheduling import services as booking
from scheduling.messages import explain
from scheduling.models import RequestStatus, Shift, ShiftPattern, SignupRequest, SignupStatus
from scheduling.services import Problem
from tests.factories import (
    PatternFactory,
    ShiftFactory,
    StaffFactory,
    TrainingTypeFactory,
    UserFactory,
    at,
)
from tests.test_plain_language import banned_words_in

pytestmark = pytest.mark.django_db


def ready(**kwargs):
    """A volunteer who can take shifts that need no training."""
    return UserFactory(profile__no_training_eligible=True, **kwargs)


def returning(**kwargs):
    """A volunteer who hasn't been active lately: every shift needs approval."""
    return ready(profile__needs_approval=True, **kwargs)


@pytest.fixture
def sent(django_capture_on_commit_callbacks):
    """`with sent():` runs the after-save emails as they run for real."""
    ShelterSettings.load()
    return lambda: django_capture_on_commit_callbacks(execute=True)


# The rule


def test_approval_comes_from_the_shift_or_the_person_never_for_staff():
    event, plain = ShiftFactory(needs_approval=True), ShiftFactory()
    assert booking.needs_approval(ready(), event)
    assert not booking.needs_approval(ready(), plain)
    assert booking.needs_approval(returning(), plain)
    assert not booking.needs_approval(StaffFactory(), event)


def test_signing_up_yourself_is_refused_when_approval_is_needed():
    result = booking.sign_up(ready(), ShiftFactory(needs_approval=True))
    assert result.problem == Problem.NEEDS_APPROVAL
    assert "please request it" in explain(result)
    assert booking.sign_up(returning(), ShiftFactory()).problem == Problem.NEEDS_APPROVAL


def test_staff_adding_someone_is_their_approval():
    person, shift = returning(), ShiftFactory(needs_approval=True)
    assert booking.sign_up(person, shift, by=StaffFactory()).ok


def test_asking_holds_no_spot_and_a_double_tap_asks_once():
    person, shift = ready(), ShiftFactory(needs_approval=True, capacity=1)
    first = booking.ask_to_join(person, shift)
    second = booking.ask_to_join(person, shift)
    assert first.ok and second.ok and second.already
    assert SignupRequest.objects.filter(shift=shift, status=RequestStatus.WAITING).count() == 1
    assert booking.confirmed_count(shift) == 0
    assert AuditEvent.objects.filter(action="request.asked", target_user=person).exists()


def test_asking_uses_the_same_checks_as_signing_up():
    untrained = ShiftFactory(needs_approval=True, required_training=TrainingTypeFactory())
    assert booking.ask_to_join(ready(), untrained).problem == Problem.NOT_ELIGIBLE
    assert booking.ask_to_join(ready(), ShiftFactory()).problem == Problem.NO_APPROVAL_NEEDED
    full = ShiftFactory(needs_approval=True, capacity=1)
    booking.sign_up(ready(), full, by=StaffFactory())
    assert booking.ask_to_join(ready(), full).problem == Problem.FULL
    person = returning()
    booking.sign_up(person, ShiftFactory(starts_at=at(2, 9)), by=StaffFactory())
    clash = ShiftFactory(starts_at=at(2, 10), needs_approval=True)
    assert booking.ask_to_join(person, clash).problem == Problem.OVERLAP


# Answering


def test_approving_books_them_emails_them_and_logs_it(sent):
    staff, person, shift = StaffFactory(), returning(), ShiftFactory()
    asked = booking.ask_to_join(person, shift).signup_request
    with sent():
        result = booking.approve_request(asked, by=staff)
    assert result.ok and result.signup.status == SignupStatus.CONFIRMED
    asked.refresh_from_db()
    assert asked.status == RequestStatus.APPROVED and asked.resolved_by == staff
    assert [m.to for m in mail.outbox] == [[person.email]]
    assert "said yes" in mail.outbox[0].body
    assert AuditEvent.objects.filter(action="request.approved", target_user=person).exists()
    assert booking.approve_request(asked, by=staff).problem == Problem.ALREADY_ANSWERED


def test_approving_a_full_shift_explains_and_keeps_them_waiting():
    staff, shift = StaffFactory(), ShiftFactory(capacity=1, needs_approval=True)
    asked = booking.ask_to_join(ready(), shift).signup_request
    booking.sign_up(ready(), shift, by=staff)
    result = booking.approve_request(asked, by=staff)
    assert result.problem == Problem.FULL
    asked.refresh_from_db()
    assert asked.status == RequestStatus.WAITING


def test_saying_no_sends_a_kind_email_with_the_note(sent):
    person, shift = ready(), ShiftFactory(needs_approval=True)
    asked = booking.ask_to_join(person, shift).signup_request
    with sent():
        booking.decline_request(asked, by=StaffFactory(), note="We have enough people this time.")
    asked.refresh_from_db()
    assert asked.status == RequestStatus.DECLINED
    body = mail.outbox[0].body
    assert "wasn't able to say yes" in body and "We have enough people this time." in body


def test_taking_back_a_request():
    person, shift = ready(), ShiftFactory(needs_approval=True)
    asked = booking.ask_to_join(person, shift).signup_request
    booking.withdraw_request(asked, by=person)
    asked.refresh_from_db()
    assert asked.status == RequestStatus.WITHDRAWN


def test_getting_on_the_shift_another_way_answers_the_request():
    person, shift = returning(), ShiftFactory()
    asked = booking.ask_to_join(person, shift).signup_request
    booking.sign_up(person, shift, by=StaffFactory())
    asked.refresh_from_db()
    assert asked.status == RequestStatus.APPROVED


def test_cancelling_the_shift_closes_requests_and_tells_them(sent):
    person, shift = ready(), ShiftFactory(needs_approval=True)
    asked = booking.ask_to_join(person, shift).signup_request
    with sent():
        booking.cancel_shift(shift, by=StaffFactory(), reason="Rain")
    asked.refresh_from_db()
    assert asked.status == RequestStatus.CLOSED
    assert "Thank you for offering to help" in mail.outbox[0].body


def test_unanswered_requests_close_once_the_shift_starts():
    shift = ShiftFactory(needs_approval=True, starts_at=at(1, 9))
    asked = booking.ask_to_join(ready(), shift).signup_request
    assert booking.close_past_requests(now=shift.starts_at + timedelta(minutes=1)) == 1
    asked.refresh_from_db()
    assert asked.status == RequestStatus.CLOSED


def test_turning_someone_off_closes_their_requests():
    person = ready()
    asked = booking.ask_to_join(person, ShiftFactory(needs_approval=True)).signup_request
    people.deactivate(person, by=StaffFactory())
    asked.refresh_from_db()
    assert asked.status == RequestStatus.CLOSED


def test_emails_to_people_without_an_address_are_logged_not_sent():
    person = ready(email="")
    log = send("request_approved", to="", context={"person": person, "shift": "Dog walking"})
    assert log.error == "No email address on file" and log.sent_at is None
    assert not mail.outbox
    assert EmailLog.objects.filter(error="No email address on file").exists()


# Volunteer screens


@pytest.fixture
def volunteer_client(client):
    person = returning(first_name="Mary")
    client.force_login(person)
    client.person = person
    return client


def test_volunteers_ask_in_two_steps_and_can_take_it_back(volunteer_client):
    shift = ShiftFactory(title="Adoption event")
    page = volunteer_client.get(f"/shifts/{shift.pk}/").content.decode()
    assert "Request this shift" in page and "Sign up for this shift" not in page
    assert volunteer_client.get(f"/shifts/{shift.pk}/sign-up/")["Location"] == (
        f"/shifts/{shift.pk}/ask/"
    )
    confirm = volunteer_client.get(f"/shifts/{shift.pk}/ask/").content.decode()
    assert "Request this shift?" in confirm
    assert not SignupRequest.objects.exists()
    volunteer_client.post(f"/shifts/{shift.pk}/ask/")
    assert SignupRequest.objects.filter(volunteer=volunteer_client.person).exists()
    page = volunteer_client.get(f"/shifts/{shift.pk}/").content.decode()
    assert "Waiting for approval" in page and "Pending approval" in page
    home = volunteer_client.get("/my-shifts/").content.decode()
    assert "Waiting for approval" in home and "Adoption event" in home
    volunteer_client.post(f"/shifts/{shift.pk}/take-back/")
    assert SignupRequest.objects.get().status == RequestStatus.WITHDRAWN


def test_day_and_find_pages_say_ask_to_join(volunteer_client):
    shift = ShiftFactory(starts_at=at(1, 9))
    find = volunteer_client.get("/shifts/").content.decode()
    assert f"/shifts/{shift.pk}/ask/" in find and f"/shifts/{shift.pk}/sign-up/" not in find
    day = volunteer_client.get(f"/my-shifts/{shift.local_date.isoformat()}/").content.decode()
    assert "Request this shift" in day


def test_everyone_else_still_signs_up_directly(client):
    person = ready()
    client.force_login(person)
    shift = ShiftFactory()
    assert "Sign up for this shift" in client.get(f"/shifts/{shift.pk}/").content.decode()
    assert client.get(f"/shifts/{shift.pk}/ask/")["Location"] == f"/shifts/{shift.pk}/sign-up/"


# Staff screens


@pytest.fixture
def staff_client(client):
    staff = StaffFactory()
    client.force_login(staff)
    client.staff = staff
    return client


def test_shift_approvals_lists_requests_by_shift_and_approves(staff_client, sent):
    shift = ShiftFactory(title="Adoption event", needs_approval=True)
    minor = ready(first_name="Sam", profile__is_minor=True)
    asked = booking.ask_to_join(minor, shift).signup_request
    booking.ask_to_join(returning(first_name="Lee"), ShiftFactory(title="Laundry"))
    page = staff_client.get("/approvals/").content.decode()
    assert "Adoption event" in page and "Laundry" in page and "Minor" in page
    assert "Needs approval for every shift" in page
    assert not banned_words_in(page)
    with sent():
        response = staff_client.post(f"/approvals/{asked.pk}/approve/")
    assert response["Location"] == "/approvals/"
    asked.refresh_from_db()
    assert asked.status == RequestStatus.APPROVED
    assert "Answered in the last" in staff_client.get("/approvals/").content.decode()


def test_saying_no_on_screen_confirms_first(staff_client, sent):
    shift = ShiftFactory(needs_approval=True)
    asked = booking.ask_to_join(ready(), shift).signup_request
    confirm = staff_client.get(f"/approvals/{asked.pk}/say-no/").content.decode()
    assert "Say no to this request?" in confirm
    asked.refresh_from_db()
    assert asked.status == RequestStatus.WAITING
    with sent():
        staff_client.post(f"/approvals/{asked.pk}/say-no/", {"note": "Next time!", "back": "shift"})
    asked.refresh_from_db()
    assert asked.status == RequestStatus.DECLINED and asked.note == "Next time!"


def test_shift_page_shows_who_is_asking_and_minors(staff_client):
    shift = ShiftFactory(needs_approval=True)
    booking.sign_up(ready(first_name="Kid", profile__is_minor=True), shift, by=staff_client.staff)
    booking.ask_to_join(ready(first_name="Asker"), shift)
    page = staff_client.get(f"/schedule/shifts/{shift.pk}/").content.decode()
    assert "Staff approve each one" in page and "Requests to join" in page
    assert "Asker" in page and "Minor" in page


def test_dashboard_and_menu_point_to_approvals(staff_client):
    booking.ask_to_join(ready(first_name="Asker"), ShiftFactory(needs_approval=True))
    page = staff_client.get("/").content.decode()
    assert "Waiting for your approval (1)" in page and 'href="/approvals/"' in page


def test_the_tick_box_is_on_shifts_and_repeating_shifts(staff_client):
    day = timezone.localdate() + timedelta(days=3)
    staff_client.post(
        "/schedule/add/",
        {
            "title": "Adoption event",
            "day": day.isoformat(),
            "start_time": "10:00",
            "end_time": "14:00",
            "capacity": "20",
            "kind": "regular",
            "needs_approval": "on",
        },
    )
    assert Shift.objects.get(title="Adoption event").needs_approval
    pattern = PatternFactory()
    staff_client.post(
        f"/schedule/patterns/{pattern.pk}/",
        {
            "title": pattern.title,
            "start_time": "09:00",
            "end_time": "11:00",
            "capacity": "2",
            "kind": "regular",
            "needs_approval": "on",
        },
    )
    assert ShiftPattern.objects.get(pk=pattern.pk).needs_approval


def test_minor_and_approval_are_saved_on_the_person(staff_client):
    person = ready()
    form = {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "email": person.email,
        "phone": person.phone,
        "emergency_contact_name": "Jo",
        "emergency_contact_phone": "7405550111",
        "is_minor": "on",
        "needs_approval": "on",
    }
    staff_client.post(f"/volunteers/{person.pk}/edit/", form)
    person.profile.refresh_from_db()
    assert person.profile.is_minor and person.profile.needs_approval
    event = AuditEvent.objects.get(action="volunteer.edited", target_user=person)
    assert {"is_minor", "needs_approval"} <= set(event.details["fields"])
    page = staff_client.get(f"/volunteers/{person.pk}/").content.decode()
    assert "Yes, under 18" in page and "Needs approval for every shift" in page
