from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.html import escape

from accounts import services
from accounts.models import Status
from accounts.services import Outcome
from core.models import AuditEvent
from tests.factories import TEST_PIN, UserFactory

pytestmark = pytest.mark.django_db

WRONG_PIN = "730259"


def _try(session_request, name, pin, now, ip="203.0.113.5"):
    return services.sign_in(session_request(ip), name, pin, now=now).outcome


def test_right_name_and_pin_signs_in_ignoring_capitals_and_spaces(client, volunteer):
    messy_name = f"  {volunteer.first_name.upper()}   {volunteer.last_name.lower()} "
    response = client.post("/sign-in/", {"name": messy_name, "pin": TEST_PIN})
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert int(client.session["_auth_user_id"]) == volunteer.pk


def test_wrong_pin_and_unknown_name_look_exactly_the_same(client, volunteer):
    wrong_pin = client.post("/sign-in/", {"name": volunteer.login_name, "pin": WRONG_PIN})
    unknown = client.post("/sign-in/", {"name": "Nobody Here", "pin": WRONG_PIN})
    message = escape("That name and PIN don't match")
    assert message in wrong_pin.content.decode()
    assert message in unknown.content.decode()
    assert "_auth_user_id" not in client.session


def test_forgot_pin_hint_appears_after_three_misses(client, volunteer):
    for _ in range(2):
        html = client.post("/sign-in/", {"name": volunteer.login_name, "pin": WRONG_PIN})
    assert "Forgot your PIN?" not in html.content.decode()
    html = client.post("/sign-in/", {"name": volunteer.login_name, "pin": WRONG_PIN})
    assert "Forgot your PIN?" in html.content.decode()


def test_account_locks_on_the_fifth_miss_and_unlocks_after_fifteen_minutes(
    session_request, volunteer
):
    now = timezone.now()
    for _ in range(4):
        assert _try(session_request, volunteer.login_name, WRONG_PIN, now) == Outcome.WRONG
    assert _try(session_request, volunteer.login_name, WRONG_PIN, now) == Outcome.LOCKED
    # Even the right PIN is refused while locked.
    assert _try(session_request, volunteer.login_name, TEST_PIN, now) == Outcome.LOCKED
    later = now + timedelta(minutes=15, seconds=1)
    assert _try(session_request, volunteer.login_name, TEST_PIN, later) == Outcome.SIGNED_IN


def test_misses_older_than_fifteen_minutes_are_forgotten(session_request, volunteer):
    now = timezone.now()
    for _ in range(4):
        _try(session_request, volunteer.login_name, WRONG_PIN, now)
    later = now + timedelta(minutes=16)
    assert _try(session_request, volunteer.login_name, WRONG_PIN, later) == Outcome.WRONG


def test_a_successful_sign_in_resets_the_count(session_request, volunteer):
    now = timezone.now()
    for _ in range(4):
        _try(session_request, volunteer.login_name, WRONG_PIN, now)
    assert _try(session_request, volunteer.login_name, TEST_PIN, now) == Outcome.SIGNED_IN
    later = now + timedelta(seconds=1)
    assert _try(session_request, volunteer.login_name, WRONG_PIN, later) == Outcome.WRONG


def test_third_lockout_in_a_day_needs_a_new_setup_link(session_request, volunteer):
    now = timezone.now()
    outcome = None
    for round_number in range(3):
        moment = now + timedelta(minutes=20 * round_number)
        for _ in range(5):
            outcome = _try(session_request, volunteer.login_name, WRONG_PIN, moment)
    assert outcome == Outcome.NEEDS_NEW_LINK
    hours_later = now + timedelta(hours=3)
    assert (
        _try(session_request, volunteer.login_name, TEST_PIN, hours_later) == Outcome.NEEDS_NEW_LINK
    )
    volunteer.refresh_from_db()
    assert volunteer.pin_reset_required
    actions = list(
        AuditEvent.objects.filter(target_user=volunteer).values_list("action", flat=True)
    )
    assert actions.count("account.locked_out") == 3
    assert "account.needs_new_link" in actions


def test_lockouts_more_than_a_day_apart_do_not_add_up(session_request, volunteer):
    now = timezone.now()
    for day in range(3):
        moment = now + timedelta(hours=25 * day)
        for _ in range(5):
            outcome = _try(session_request, volunteer.login_name, WRONG_PIN, moment)
        assert outcome == Outcome.LOCKED


def test_unknown_names_lock_like_real_ones(session_request, db):
    now = timezone.now()
    outcomes = [_try(session_request, "Nobody Here", WRONG_PIN, now) for _ in range(5)]
    assert outcomes[-1] == Outcome.LOCKED


def test_device_is_blocked_after_twenty_misses_across_names(session_request, volunteer):
    now = timezone.now()
    for i in range(20):
        _try(session_request, f"Guess Name{i}", WRONG_PIN, now, ip="198.51.100.7")
    blocked = _try(session_request, volunteer.login_name, TEST_PIN, now, ip="198.51.100.7")
    assert blocked == Outcome.DEVICE_BLOCKED
    other_device = _try(session_request, volunteer.login_name, TEST_PIN, now, ip="198.51.100.8")
    assert other_device == Outcome.SIGNED_IN


def test_turned_off_account_is_told_only_after_the_right_pin(session_request, db):
    person = UserFactory(status=Status.INACTIVE)
    now = timezone.now()
    assert _try(session_request, person.login_name, WRONG_PIN, now) == Outcome.WRONG
    assert _try(session_request, person.login_name, TEST_PIN, now) == Outcome.TURNED_OFF


def test_person_without_a_pin_yet_cannot_sign_in(session_request, db):
    person = UserFactory()
    person.set_unusable_password()
    person.save()
    assert _try(session_request, person.login_name, TEST_PIN, timezone.now()) == Outcome.WRONG


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("volunteer", timedelta(days=30)), ("staff", timedelta(hours=12))],
)
def test_sign_in_length_depends_on_role(client, request, fixture, expected):
    person = request.getfixturevalue(fixture)
    client.post("/sign-in/", {"name": person.login_name, "pin": TEST_PIN})
    assert client.session.get_expiry_age() == int(expected.total_seconds())


def test_after_sign_in_only_same_site_pages_are_followed(client, volunteer):
    evil = client.post(
        "/sign-in/?next=https://evil.example.com/",
        {"name": volunteer.login_name, "pin": TEST_PIN, "next": "https://evil.example.com/"},
    )
    assert evil["Location"] == "/"
    client.logout()
    ok = client.post(
        "/sign-in/", {"name": volunteer.login_name, "pin": TEST_PIN, "next": "/styleguide/"}
    )
    assert ok["Location"] == "/styleguide/"


def test_signed_in_person_visiting_sign_in_goes_home(client, volunteer):
    client.force_login(volunteer)
    assert client.get("/sign-in/")["Location"] == "/"


def test_sign_out_is_a_button_not_a_link(client, volunteer):
    client.force_login(volunteer)
    assert client.get("/sign-out/").status_code == 405
    response = client.post("/sign-out/")
    assert response["Location"] == "/sign-in/"
    assert "_auth_user_id" not in client.session


def test_lock_clears_on_successful_sign_in(session_request, volunteer):
    now = timezone.now()
    for _ in range(5):
        _try(session_request, volunteer.login_name, WRONG_PIN, now)
    _try(session_request, volunteer.login_name, TEST_PIN, now + timedelta(minutes=16))
    volunteer.refresh_from_db()
    assert volunteer.locked_until is None


@pytest.mark.parametrize(
    ("count", "forwarded", "remote", "expected"),
    [
        (0, "1.1.1.1", "10.0.0.1", "10.0.0.1"),
        (1, "1.1.1.1", "10.0.0.1", "1.1.1.1"),
        (1, "6.6.6.6, 1.1.1.1", "10.0.0.1", "1.1.1.1"),
        (2, "6.6.6.6, 1.1.1.1, 172.16.0.2", "10.0.0.1", "1.1.1.1"),
        (1, "", "10.0.0.1", "10.0.0.1"),
        (0, "", "not-an-address", None),
    ],
)
def test_client_ip_trusts_only_our_proxies(rf, settings, count, forwarded, remote, expected):
    settings.TRUSTED_PROXY_COUNT = count
    request = rf.get("/", REMOTE_ADDR=remote, HTTP_X_FORWARDED_FOR=forwarded)
    assert services.client_ip(request) == expected
