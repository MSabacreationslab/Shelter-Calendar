"""Usage, hotspots and problem alerts for the Admin, and the Admin page for staff areas."""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from accounts.models import LoginAttempt
from core import audit, errors
from insights import problems, queries
from insights.models import PageView, Problem
from tests.factories import AdminFactory, StaffFactory, UserFactory

pytestmark = pytest.mark.django_db

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148"


# Page visits


def test_each_page_visit_is_recorded_by_name_not_address(client):
    person = UserFactory()
    client.force_login(person)
    client.get("/my-shifts/2026-10-06/", HTTP_USER_AGENT=IPHONE, HTTP_REFERER="http://testserver/")
    visit = PageView.objects.get()
    assert visit.route == "shifts:day" and visit.user == person and visit.role == "volunteer"
    assert visit.device == "phone" and visit.came_from == "home" and visit.status == 200
    assert "2026" not in visit.route


def test_health_checks_and_unknown_pages_are_not_counted(client):
    client.get("/healthz")
    client.get("/no-such-page/")
    assert not PageView.objects.exists()


def test_a_form_sent_back_to_fix_is_flagged(client):
    client.force_login(UserFactory())
    client.post("/profile/", {"phone": "123"})
    assert PageView.objects.get(method="POST").form_problem


# Problem alerts


@pytest.fixture
def admin():
    return AdminFactory(email="mike@example.com")


def _alerts():
    return [m for m in mail.outbox if m.subject.startswith("[Shelter app]")]


def test_a_signed_in_persons_problem_emails_the_admin(client, admin):
    client.force_login(UserFactory())
    response = client.get("/admin/")
    assert response.status_code == 403
    assert "let the admin know automatically" in response.content.decode()
    alert = _alerts()[0]
    assert alert.to == ["mike@example.com"]
    assert "SC-102" in alert.subject and "dashboard:admin" in alert.subject
    assert "Who: Pat" in alert.body and "(Volunteer)" in alert.body
    assert Problem.objects.get().emailed


def test_signed_out_page_not_found_is_recorded_but_not_emailed(client, admin):
    html = client.get("/wp-login.php").content.decode()
    assert Problem.objects.get().code == errors.PAGE_NOT_FOUND.code
    assert not _alerts()
    assert "let the admin know" not in html


@pytest.mark.urls("tests.urls")
def test_server_errors_email_the_traceback_even_when_signed_out(settings, admin):
    settings.DEBUG = False
    Client(raise_request_exception=False).get("/test/boom/")
    alert = _alerts()[0]
    assert "SC-104" in alert.subject
    assert "RuntimeError: Deliberate failure" in alert.body and "Traceback" in alert.body
    assert "Traceback" in Problem.objects.get().details


def test_the_same_problem_is_emailed_once_an_hour(client, admin):
    client.force_login(UserFactory())
    client.get("/admin/")
    second = client.get("/admin/").content.decode()
    assert len(_alerts()) == 1
    assert Problem.objects.count() == 2
    assert "let the admin know" in second


def test_alerts_can_go_to_a_set_address(client, admin, settings):
    settings.PROBLEM_EMAILS = ["alerts@example.com"]
    client.force_login(UserFactory())
    client.get("/admin/")
    assert _alerts()[0].to == ["alerts@example.com"]


def test_without_anyone_to_tell_the_page_does_not_claim_it(client):
    client.force_login(UserFactory())
    assert "let the admin know" not in client.get("/admin/").content.decode()
    assert Problem.objects.exists()


def test_a_failed_email_is_reported(admin, monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def attach_alternative(self, *args):
            pass

        def send(self):
            raise ConnectionError("Mail server down")

    monkeypatch.setattr("notifications.email.EmailMultiAlternatives", Broken)
    from notifications.email import send

    send("request_approved", to="x@example.com", context={"person": admin, "shift": "Dog walking"})
    problem = Problem.objects.get()
    assert problem.code == errors.EMAIL_FAILED.code and problem.route == "email: request_approved"
    assert "SC-501" in _alerts()[0].subject


def test_a_crashed_scheduled_task_is_reported(admin, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Database went away")

    monkeypatch.setattr(
        "scheduling.management.commands.expire_waitlists.expire_past_waitlists", fail
    )
    with pytest.raises(RuntimeError):
        call_command("expire_waitlists")
    problem = Problem.objects.get()
    assert problem.code == errors.TASK_FAILED.code and problem.route == "task: expire_waitlists"
    assert "Database went away" in _alerts()[0].body


def test_a_mistyped_command_is_not_a_problem(admin):
    with pytest.raises(CommandError):
        call_command("send_reminders", "--date", "someday")
    assert not Problem.objects.exists()


def test_reporting_never_raises(monkeypatch):
    monkeypatch.setattr(problems, "_save", lambda *args: 1 / 0)
    assert problems.report(errors.SERVER_ERROR, route="x") is False


# The Admin's pages


def test_the_admin_can_send_a_test_alert(client, admin):
    client.force_login(admin)
    client.post("/admin/problems/test/")
    client.post("/admin/problems/test/")
    assert len([m for m in _alerts() if "SC-107" in m.subject]) == 2
    html = client.get("/admin/problems/").content.decode()
    assert "SC-107" in html and "mike@example.com" in html


def test_usage_hotspots_and_problems_are_for_the_admin_only(client, admin):
    client.force_login(StaffFactory())
    for path in ("/admin/usage/", "/admin/hotspots/", "/admin/problems/"):
        assert client.get(path).status_code == 403
    client.force_login(admin)
    for path in ("/admin/usage/?days=7", "/admin/hotspots/?days=90", "/admin/problems/"):
        assert client.get(path).status_code == 200


def _visit(person, route, minutes_ago=0, **fields):
    return PageView.objects.create(
        user=person,
        role=person.role if person else "",
        route=route,
        method=fields.pop("method", "GET"),
        status=fields.pop("status", 200),
        duration_ms=fields.pop("duration_ms", 100),
        device=fields.pop("device", "computer"),
        at=timezone.now() - timedelta(minutes=minutes_ago),
        **fields,
    )


def test_usage_counts_people_pages_devices_and_sign_ins():
    mary, robin = UserFactory(), StaffFactory()
    _visit(mary, "shifts:home", device="phone")
    _visit(mary, "shifts:find", device="phone")
    _visit(robin, "home")
    _visit(robin, "home", minutes_ago=60 * 24 * 40)  # outside 30 days
    LoginAttempt.objects.create(name_entered="mary", user=mary, succeeded=True)
    LoginAttempt.objects.create(name_entered="mary", user=mary, succeeded=False)
    audit.record("shift.signed_up", actor=mary, target_user=mary)
    numbers = queries.usage(30)
    assert numbers["people"] == 2 and numbers["volunteers"] == 1 and numbers["staff"] == 1
    assert numbers["pages"] == 3 and numbers["sign_ins"] == 1 and numbers["wrong_pins"] == 1
    assert numbers["signed_up"] == 1
    assert numbers["devices"][0] == {"device": "phone", "n": 2, "share": 67}
    assert len(numbers["daily"]) == 30 and numbers["daily"][0]["pages"] == 3


def test_hotspots_find_paths_struggles_and_back_and_forth():
    mary = UserFactory()
    for minutes in (9, 6, 3):
        _visit(mary, "shifts:find", minutes_ago=minutes, came_from="shifts:home")
        _visit(mary, "shifts:home", minutes_ago=minutes - 1)
    _visit(mary, "people:profile", method="POST", form_problem=True)
    _visit(mary, "people:profile", method="POST", status=302)
    found = queries.hotspots(30)
    assert found["pages"][0]["name"] in ("Find a shift", "My shifts (calendar)")
    assert found["paths"][0]["from_name"] == "My shifts (calendar)"
    assert found["paths"][0]["to_name"] == "Find a shift" and found["paths"][0]["n"] == 3
    assert found["forms"] == [
        {"route": "people:profile", "sent": 2, "problems": 1, "name": "My profile", "rate": 50}
    ]
    assert {row["route"] for row in found["repeats"]} == {"shifts:find", "shifts:home"}


def test_old_visits_and_problems_are_pruned():
    _visit(None, "home", minutes_ago=60 * 24 * 91)
    _visit(None, "home")
    Problem.objects.create(code="SC-104", at=timezone.now() - timedelta(days=400))
    call_command("prune_usage")
    assert PageView.objects.count() == 1 and not Problem.objects.exists()


# The Admin page and the shorter menu


def test_staff_menu_has_four_items_and_admin_holds_the_rest(client):
    client.force_login(StaffFactory())
    html = client.get("/schedule/").content.decode()
    start = html.index('<nav class="site-nav"')
    menu = html[start : html.index("</nav>", start)]
    assert menu.count("<li>") == 4
    assert 'href="/admin/" aria-current="page">Admin</a>' in menu
    hub = client.get("/admin/").content.decode()
    for label in ("Shift approvals", "Schedule", "Volunteers", "Training", "Change log", "Staff"):
        assert label in hub
    assert "Admin only" not in hub and "/admin/usage/" not in hub


def test_the_admin_sees_their_own_section(client, admin):
    client.force_login(admin)
    hub = client.get("/admin/").content.decode()
    assert "Admin only" in hub
    for path in ("/settings/", "/admin/usage/", "/admin/hotspots/", "/admin/problems/"):
        assert f'href="{path}"' in hub
