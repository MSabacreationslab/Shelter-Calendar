"""Staff dashboard (SPEC §6, Phase 6): today, needs attention, directory, change log, settings."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from accounts import services as account_services
from accounts.models import Role, SetupLinkPurpose, Status, User
from core.models import AuditEvent, ShelterSettings
from scheduling import services as booking
from scheduling.models import ShiftKind, Signup, SignupStatus, WaitlistEntry, WaitlistStatus
from tests.factories import (
    AdminFactory,
    ShiftFactory,
    StaffFactory,
    TrainingTypeFactory,
    UserFactory,
    at,
    trained,
)

pytestmark = pytest.mark.django_db


def ready(**kwargs):
    return UserFactory(profile__no_training_eligible=True, **kwargs)


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def sent(django_capture_on_commit_callbacks):
    ShelterSettings.load()
    ShelterSettings.objects.update(notify_emails="lead@example.com")
    return lambda: django_capture_on_commit_callbacks(execute=True)


def later_today(hours):
    return timezone.now() + timedelta(hours=hours)


# The dashboard


def test_today_lists_shifts_with_names_and_open_spots(staff_client):
    start = timezone.localtime().replace(hour=23, minute=0, second=0, microsecond=0)
    shift = ShiftFactory(
        title="Evening cats", starts_at=start, ends_at=start + timedelta(minutes=50)
    )
    Signup.objects.create(
        shift=shift, volunteer=ready(first_name="Mary"), period=(shift.starts_at, shift.ends_at)
    )
    html = staff_client.get("/").content.decode()
    assert "Evening cats" in html
    assert "Mary Tester" in html
    assert "1 of 3 filled, 2 open" in html


def test_urgent_cancellations_come_first_and_routine_ones_are_listed_below(staff_client, sent):
    urgent_shift = ShiftFactory(title="Soon shift", starts_at=later_today(5))
    routine_shift = ShiftFactory(title="Later shift", starts_at=at(5, 9))
    for shift, name in ((urgent_shift, "Urgent"), (routine_shift, "Routine")):
        person = ready(first_name=name)
        signup = booking.sign_up(person, shift).signup
        with sent():
            booking.cancel_signup(signup, by=person, reason="Sorry")
    html = staff_client.get("/").content.decode()
    assert "Urgent: 1 cancellation" in html
    assert html.index("Urgent Tester") < html.index("Other cancellations this week")
    assert html.index("Routine Tester") > html.index("Other cancellations this week")


def test_urgent_threshold_can_be_48_hours(sent):
    ShelterSettings.objects.update(urgent_threshold_hours=48)
    person = ready()
    shift = ShiftFactory(starts_at=later_today(30))
    signup = booking.sign_up(person, shift).signup
    with sent():
        result = booking.cancel_signup(signup, by=person)
    signup.refresh_from_db()
    assert not result.late and signup.was_urgent
    assert [m.to for m in mail.outbox] == [["lead@example.com"]]


def test_urgency_is_kept_when_the_threshold_changes_later(sent):
    person = ready()
    signup = booking.sign_up(person, ShiftFactory(starts_at=later_today(30))).signup
    booking.cancel_signup(signup, by=person)
    ShelterSettings.objects.update(urgent_threshold_hours=48)
    signup.refresh_from_db()
    assert not signup.was_urgent


def test_needs_attention_lists(staff_client):
    now = timezone.now()
    short = ShiftFactory(title="Short shift", starts_at=at(2, 9))
    full = ShiftFactory(title="Waiting shift", starts_at=at(3, 9), capacity=1)
    first = ready()
    signup = booking.sign_up(first, full).signup
    booking.join_waitlist(ready(first_name="Waiter"), full)
    booking.cancel_signup(signup, by=first)
    newbie = UserFactory(first_name="Linkless")
    newbie.set_unusable_password()
    newbie.save()
    account_services.create_setup_link(
        newbie, purpose=SetupLinkPurpose.INVITE, now=now - timedelta(days=8)
    )
    locked = UserFactory(first_name="Locked", pin_reset_required=True)
    html = staff_client.get("/").content.decode()
    assert "Short shift" in html
    assert "A spot opened and someone is waiting" in html and "Waiting shift" in html
    assert "Linkless Tester" in html
    assert "Locked Tester" in html
    assert short and locked


def test_orientation_conflicts_show_until_they_are_rebooked(staff_client):
    topic = TrainingTypeFactory(name="Orientation", is_orientation=True)
    session = ShiftFactory(kind=ShiftKind.TRAINING, teaches=topic, starts_at=at(4, 10))
    person = UserFactory(first_name="Conflict")
    signup = booking.sign_up(person, session, by=StaffFactory()).signup
    Signup.objects.filter(pk=signup.pk).update(conflict_reported_at=timezone.now())
    assert "Conflict Tester" in staff_client.get("/").content.decode()
    booking.cancel_signup(signup, by=StaffFactory())
    assert "Conflict Tester" not in staff_client.get("/").content.decode()


def test_all_clear_when_nothing_needs_attention(staff_client):
    assert "All clear" in staff_client.get("/").content.decode()


# Directory and person page


def test_directory_filters_by_role_and_training(staff_client):
    dogs = TrainingTypeFactory(name="Dog walking")
    walker = UserFactory(first_name="Walker")
    trained(walker, dogs)
    UserFactory(first_name="Plain")
    StaffFactory(first_name="Lead")
    html = staff_client.get("/volunteers/?who=staff").content.decode()
    assert "Lead Tester" in html and "Plain Tester" not in html
    html = staff_client.get(f"/volunteers/?done={dogs.pk}").content.decode()
    assert "Walker Tester" in html and "Plain Tester" not in html


def test_person_page_shows_shifts_and_recent_changes(staff_client):
    person = ready()
    booking.sign_up(person, ShiftFactory(title="Upcoming walk", starts_at=at(3, 9)))
    html = staff_client.get(f"/volunteers/{person.pk}/").content.decode()
    assert "Upcoming walk" in html
    assert "Signed up for a shift" in html


def test_turning_someone_off_takes_them_off_future_shifts(staff_client, client):
    person = ready()
    future = ShiftFactory(title="Future walk", starts_at=at(3, 9), capacity=1)
    booking.sign_up(person, future)
    other_full = ShiftFactory(starts_at=at(4, 9), capacity=1)
    booking.sign_up(ready(), other_full)
    booking.join_waitlist(person, other_full)
    confirm = staff_client.get(f"/volunteers/{person.pk}/turn-off/").content.decode()
    assert "Future walk" in confirm
    staff_client.post(f"/volunteers/{person.pk}/turn-off/")
    person.refresh_from_db()
    assert person.status == Status.INACTIVE and person.deactivated_at
    assert Signup.objects.get(volunteer=person).status == SignupStatus.CANCELLED
    assert WaitlistEntry.objects.get(volunteer=person).status == WaitlistStatus.REMOVED
    staff_client.post(f"/volunteers/{person.pk}/turn-on/")
    person.refresh_from_db()
    assert person.status == Status.ACTIVE


def test_nobody_can_turn_off_the_admin(staff_client):
    admin = AdminFactory()
    assert staff_client.get(f"/volunteers/{admin.pk}/turn-off/").status_code == 404


def test_view_as_volunteer_is_read_only_and_logged(staff_client, staff):
    person = ready(first_name="Viewed")
    booking.sign_up(person, ShiftFactory(title="Their walk", starts_at=at(2, 9)))
    html = staff_client.get(f"/volunteers/{person.pk}/view-as/").content.decode()
    assert "Viewing as Viewed Tester: read only" in html
    assert ", Viewed</h1>" in html
    assert "Their walk" in html
    assert 'href="/shifts/' not in html and 'href="/my-shifts/20' not in html
    assert AuditEvent.objects.filter(
        action="volunteer.viewed_as", actor=staff, target_user=person
    ).exists()


def test_view_as_is_for_volunteers_only(staff_client):
    assert staff_client.get(f"/volunteers/{StaffFactory().pk}/view-as/").status_code == 404


# Change log, staff and settings


def test_change_log_filters_by_person_and_pages(staff_client):
    person = ready(first_name="Logged")
    for _ in range(3):
        booking.sign_up(person, ShiftFactory(starts_at=at(2, 9)))
        Signup.objects.filter(volunteer=person).update(status=SignupStatus.CANCELLED)
    other = ready(first_name="Other")
    booking.sign_up(other, ShiftFactory(starts_at=at(5, 9)))
    html = staff_client.get(f"/changes/?person={person.pk}").content.decode()
    # Check the list itself; the "About" drop-down names everyone.
    assert f'href="/volunteers/{person.pk}/"' in html
    assert f'href="/volunteers/{other.pk}/"' not in html
    assert "Signed up for a shift" in html


def test_staff_can_add_staff_and_change_job_titles(
    staff_client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        staff_client.post(
            "/staff/add/",
            {
                "first_name": "Casey",
                "last_name": "New",
                "job_title": "Volunteer Lead's Assistant",
                "email": "casey@example.com",
                "phone": "7405550123",
            },
        )
    casey = User.objects.get(login_name="Casey New")
    assert casey.role == Role.STAFF and casey.job_title == "Volunteer Lead's Assistant"
    assert mail.outbox[-1].to == ["casey@example.com"]
    staff_client.post(f"/volunteers/{casey.pk}/job-title/", {"job_title": "Shelter Lead"})
    casey.refresh_from_db()
    assert casey.job_title == "Shelter Lead"
    assert "Casey New" in staff_client.get("/staff/").content.decode()


def test_the_admin_is_never_listed_as_staff(staff_client):
    admin = AdminFactory(first_name="Boss")
    assert admin.get_full_name() not in staff_client.get("/staff/").content.decode()


def test_settings_are_admin_only_and_logged(client):
    client.force_login(StaffFactory())
    assert client.get("/settings/").status_code == 403
    admin = AdminFactory()
    client.force_login(admin)
    ShelterSettings.load()
    response = client.post(
        "/settings/",
        {
            "shelter_name": "Test Shelter",
            "shelter_phone": "(740) 555-0100",
            "shelter_email": "",
            "self_cancel_hours": "24",
            "urgent_threshold_hours": "48",
            "notify_emails": "lead@example.com\n\n  second@example.com  ",
        },
    )
    assert response["Location"] == "/settings/"
    row = ShelterSettings.load()
    assert row.urgent_threshold_hours == 48
    assert row.notify_email_list == ["lead@example.com", "second@example.com"]
    event = AuditEvent.objects.get(action="settings.changed")
    assert event.details["changes"]["urgent_threshold_hours"] == {"from": 24, "to": 48}


def test_bad_notify_emails_are_explained(client):
    client.force_login(AdminFactory())
    html = client.post(
        "/settings/",
        {
            "shelter_name": "Test Shelter",
            "self_cancel_hours": "24",
            "urgent_threshold_hours": "24",
            "notify_emails": "not-an-email",
        },
    ).content.decode()
    assert "doesn&#x27;t look like an email address" in html
