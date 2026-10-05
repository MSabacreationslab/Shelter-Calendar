from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts import services
from accounts.models import LoginAttempt, Role, User
from core.models import AuditEvent
from scheduling.models import Shift, Signup, SignupStatus, WaitlistEntry
from tests.factories import StaffFactory
from training.models import TrainingType

pytestmark = pytest.mark.django_db

DEMO_PIN = "905184"


def _run(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def test_create_admin_makes_the_admin_and_prints_a_link():
    output = _run("create_admin", "Mike Saba", "mike@example.com")
    admin = User.objects.get(login_name="Mike Saba")
    assert admin.role == Role.ADMIN and admin.is_superuser and admin.is_staff
    assert not admin.has_usable_password()
    token = output.strip().splitlines()[-1].rsplit("/welcome/", 1)[1].strip("/")
    assert services.find_valid_link(token) is not None
    assert AuditEvent.objects.filter(action="account.created", target_user=admin).exists()


def test_create_admin_refuses_duplicates_but_can_send_a_new_link():
    _run("create_admin", "Mike Saba", "mike@example.com")
    with pytest.raises(CommandError):
        _run("create_admin", "mike saba", "other@example.com")
    assert "/welcome/" in _run("create_admin", "Mike Saba", "--new-link")


def test_seed_demo_refuses_outside_demo_mode(settings):
    settings.DEMO_MODE = False
    with pytest.raises(CommandError):
        _run("seed_demo")


def test_seed_demo_fills_the_test_site_once(settings, monkeypatch, client):
    settings.DEMO_MODE = True
    monkeypatch.setenv("DEMO_PIN", DEMO_PIN)
    _run("seed_demo")
    assert User.objects.filter(role=Role.STAFF).count() == 3
    assert User.objects.filter(role=Role.VOLUNTEER).count() == 10
    assert TrainingType.objects.filter(is_orientation=True).count() == 1
    assert "Created 0" in _run("seed_demo")
    # A lived-in schedule: four weeks of staffed shifts, a waitlist, requests and a cancellation.
    confirmed = Signup.objects.filter(status=SignupStatus.CONFIRMED)
    assert confirmed.count() >= 40
    assert confirmed.values("volunteer").distinct().count() >= 8
    assert WaitlistEntry.objects.exists()
    assert (
        Shift.objects.filter(starts_at__gt=timezone.now()).exclude(signups__isnull=False).exists()
    )
    event = Shift.objects.get(title="Adoption event")
    assert event.needs_approval and event.requests.count() == 2
    jordan = User.objects.get(first_name="Jordan")
    assert jordan.profile.needs_approval and jordan.signup_requests.count() == 2
    assert not jordan.signups.exists()
    assert User.objects.filter(profile__is_minor=True).count() == 1
    assert Signup.objects.filter(was_urgent=True, status=SignupStatus.CANCELLED).count() == 1
    assert not mail.outbox
    response = client.post("/sign-in/", {"name": "robin demo", "pin": DEMO_PIN})
    assert response.status_code == 302


def test_seed_demo_needs_a_valid_pin(settings, monkeypatch):
    settings.DEMO_MODE = True
    monkeypatch.setenv("DEMO_PIN", "123456")
    with pytest.raises(CommandError):
        _run("seed_demo")


def test_prune_keeps_recent_sign_in_attempts():
    old = LoginAttempt.objects.create(
        name_entered="x", succeeded=False, created_at=timezone.now() - timedelta(days=91)
    )
    recent = LoginAttempt.objects.create(name_entered="y", succeeded=False)
    _run("prune_login_attempts")
    remaining = set(LoginAttempt.objects.values_list("pk", flat=True))
    assert remaining == {recent.pk}
    assert old.pk not in remaining


def test_setup_link_prints_a_working_link_for_anyone(client, settings):
    settings.SITE_URL = "https://example.test"
    person = StaffFactory(first_name="Cindy", last_name="Grigsby", login_name="Cindy Grigsby")
    person.set_unusable_password()
    person.save()
    out = _run("setup_link", "cindy grigsby")
    link = out.strip().splitlines()[-1]
    assert link.startswith("https://example.test/")
    page = client.get(link.replace("https://example.test", ""))
    assert page.status_code == 200 and "Cindy" in page.content.decode()


def test_setup_link_explains_a_wrong_name():
    with pytest.raises(CommandError, match="Nobody signs in as"):
        _run("setup_link", "No Such Person")
