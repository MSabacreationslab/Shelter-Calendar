from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from django.utils.html import escape

from accounts import services
from accounts.models import SetupLink, SetupLinkPurpose, Status
from accounts.pins import TOO_EASY
from core import errors
from core.models import AuditEvent
from tests.factories import TEST_PIN, UserFactory

pytestmark = pytest.mark.django_db

NEW_PIN = "905184"


@pytest.fixture
def newcomer(db):
    """Someone just added, who hasn't chosen a PIN yet."""
    person = UserFactory()
    person.set_unusable_password()
    person.save()
    return person


def _link(person, **kwargs):
    return services.create_setup_link(person, purpose=SetupLinkPurpose.INVITE, **kwargs)


def test_only_a_hash_of_the_token_is_stored(newcomer):
    token = _link(newcomer)
    stored = SetupLink.objects.get(user=newcomer)
    assert stored.token_hash == services.hash_token(token)
    assert token not in stored.token_hash
    assert services.setup_link_url(token).endswith(f"/welcome/{token}/")


def test_opening_the_link_does_not_use_it_up(client, newcomer):
    token = _link(newcomer)
    assert client.get(f"/welcome/{token}/").status_code == 200
    assert client.get(f"/welcome/{token}/").status_code == 200
    assert SetupLink.objects.get(user=newcomer).used_at is None


def test_choosing_a_pin_signs_in_and_uses_the_link(client, newcomer):
    token = _link(newcomer)
    response = client.post(f"/welcome/{token}/", {"pin": NEW_PIN, "pin_again": NEW_PIN})
    assert response["Location"] == "/"
    assert int(client.session["_auth_user_id"]) == newcomer.pk
    newcomer.refresh_from_db()
    assert newcomer.check_password(NEW_PIN)
    assert SetupLink.objects.get(user=newcomer).used_at is not None
    assert AuditEvent.objects.filter(action="account.pin_set", target_user=newcomer).exists()
    again = client.get(f"/welcome/{token}/")
    assert again.status_code == 410
    assert errors.LINK_EXPIRED.code in again.content.decode()


def test_links_expire_after_seven_days(client, newcomer):
    token = _link(newcomer, now=timezone.now() - timedelta(days=7, minutes=1))
    response = client.get(f"/welcome/{token}/")
    assert response.status_code == 410
    assert escape(errors.LINK_EXPIRED.title) in response.content.decode()


def test_a_new_link_replaces_older_ones(client, newcomer):
    old = _link(newcomer)
    new = _link(newcomer)
    assert client.get(f"/welcome/{old}/").status_code == 410
    assert client.get(f"/welcome/{new}/").status_code == 200


def test_easy_or_mismatched_pins_are_refused(client, newcomer):
    token = _link(newcomer)
    easy = client.post(f"/welcome/{token}/", {"pin": "123456", "pin_again": "123456"})
    assert escape(TOO_EASY) in easy.content.decode()
    mismatch = client.post(f"/welcome/{token}/", {"pin": NEW_PIN, "pin_again": "905185"})
    assert escape("The two PINs don't match") in mismatch.content.decode()
    assert SetupLink.objects.get(user=newcomer).used_at is None


def test_setting_a_pin_clears_every_lock(newcomer):
    newcomer.locked_until = timezone.now() + timedelta(minutes=10)
    newcomer.pin_reset_required = True
    newcomer.save()
    token = services.create_setup_link(newcomer, purpose=SetupLinkPurpose.RESET)
    services.set_pin_from_link(token, NEW_PIN)
    newcomer.refresh_from_db()
    assert newcomer.locked_until is None
    assert not newcomer.pin_reset_required


def test_turned_off_people_cannot_use_a_link(client, newcomer):
    token = _link(newcomer)
    newcomer.status = Status.INACTIVE
    newcomer.save()
    assert client.get(f"/welcome/{token}/").status_code == 410
    assert services.set_pin_from_link(token, NEW_PIN) is None


def test_a_new_pin_signs_out_other_devices(client, volunteer):
    other_device = Client()
    other_device.post("/sign-in/", {"name": volunteer.login_name, "pin": TEST_PIN})
    assert other_device.get("/").status_code == 200
    token = services.create_setup_link(volunteer, purpose=SetupLinkPurpose.RESET)
    client.post(f"/welcome/{token}/", {"pin": NEW_PIN, "pin_again": NEW_PIN})
    assert other_device.get("/").status_code == 302
