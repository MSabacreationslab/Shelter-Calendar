"""Booking an orientation when adding a volunteer, and the "this time doesn't work" link."""

import re

import pytest
from django.core import mail

from accounts.models import User
from core.models import AuditEvent, ShelterSettings
from scheduling import links
from scheduling.models import ShiftKind, Signup, SignupStatus
from tests.factories import ShiftFactory, TrainingTypeFactory, UserFactory, at
from tests.test_people import _form
from training.models import TrainingNeed

pytestmark = pytest.mark.django_db


@pytest.fixture
def orientation():
    topic = TrainingTypeFactory(name="Orientation", is_orientation=True)
    return ShiftFactory(
        title="Orientation", kind=ShiftKind.TRAINING, teaches=topic, capacity=2, starts_at=at(5, 10)
    )


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def emails(django_capture_on_commit_callbacks):
    ShelterSettings.load()
    ShelterSettings.objects.update(notify_emails="lead@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        yield mail.outbox


def _conflict_link(body):
    return re.search(r"https?://\S+/orientation/\S+/", body).group(0)


def test_adding_with_an_orientation_books_it_and_emails_the_time(staff_client, orientation, emails):
    staff_client.post("/volunteers/add/", _form(orientation=orientation.pk))
    person = User.objects.get(login_name="Mary Smith")
    assert Signup.objects.filter(
        shift=orientation, volunteer=person, status=SignupStatus.CONFIRMED
    ).exists()
    assert TrainingNeed.objects.filter(volunteer=person, training_type=orientation.teaches).exists()
    body = emails[0].body
    assert "Your orientation: Orientation" in body
    assert "/orientation/" in body


def test_full_orientations_are_not_offered(staff_client, orientation):
    for _ in range(2):
        Signup.objects.create(
            shift=orientation,
            volunteer=UserFactory(),
            period=(orientation.starts_at, orientation.ends_at),
        )
    html = staff_client.get("/volunteers/add/").content.decode()
    assert f'value="{orientation.pk}"' not in html


def test_conflict_link_asks_first_then_tells_staff_once(client, staff_client, orientation, emails):
    staff_client.post("/volunteers/add/", _form(orientation=orientation.pk))
    path = "/" + _conflict_link(emails[0].body).split("/", 3)[3]
    client.logout()
    page = client.get(path)
    assert page.status_code == 200
    assert "doesn't work for me" in page.content.decode()
    signup = Signup.objects.get(shift=orientation)
    assert signup.conflict_reported_at is None

    client.post(path)
    client.post(path)
    signup.refresh_from_db()
    assert signup.conflict_reported_at is not None
    staff_emails = [m for m in emails if m.to == ["lead@example.com"]]
    assert len(staff_emails) == 1
    assert "Mary Smith" in staff_emails[0].body
    assert AuditEvent.objects.filter(action="orientation.conflict_reported").count() == 1


def test_forged_conflict_links_are_refused(client):
    assert client.get("/orientation/not-a-real-link/").status_code == 410


def test_conflict_tokens_round_trip(orientation):
    signup = Signup.objects.create(
        shift=orientation,
        volunteer=UserFactory(),
        period=(orientation.starts_at, orientation.ends_at),
    )
    assert links.signup_from_conflict_token(links.conflict_token(signup)) == signup.pk
