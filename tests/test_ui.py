"""The shared look (SPEC §7): who's signed in, the menu, the calendar, status and empty states."""

import pytest
from django.utils import timezone

from scheduling import services as booking
from tests.factories import AdminFactory, ShiftFactory, StaffFactory, UserFactory, at

pytestmark = pytest.mark.django_db


def page(client, person, path="/"):
    client.force_login(person)
    return client.get(path).content.decode()


def test_volunteers_see_a_red_volunteer_badge_and_their_menu(client):
    html = page(client, UserFactory(first_name="Jordan"))
    assert 'data-role="volunteer"' in html
    assert '<span class="role-badge role-badge--volunteer">Volunteer</span>' in html
    assert ">Home</a>" in html and ">Find a shift</a>" in html and ">My profile</a>" in html
    assert ">Dashboard</a>" not in html


def test_staff_see_a_blue_staff_badge_and_the_dashboard_link(client):
    html = page(client, StaffFactory())
    assert 'data-role="staff"' in html
    assert '<span class="role-badge role-badge--staff">Staff</span>' in html
    assert 'href="/" aria-current="page">Dashboard</a>' in html


def test_the_admin_is_shown_as_admin_in_staff_colours(client):
    html = page(client, AdminFactory())
    assert '<span class="role-badge role-badge--admin">Admin</span>' in html


def test_sign_out_sits_apart_from_the_menu(client):
    html = page(client, UserFactory())
    start = html.index('<nav class="site-nav')
    menu = html[start : html.index("</nav>", start)]
    assert "Sign out" not in menu
    assert 'class="btn btn--quiet">Sign out</button>' in html


def test_only_the_current_page_is_marked_in_the_menu(client):
    person = StaffFactory()
    html = page(client, person, "/my-shifts/")
    assert html.count('aria-current="page"') == 1
    assert 'href="/my-shifts/" aria-current="page">My shifts</a>' in html


def test_calendar_has_a_today_button_and_clear_marks(client):
    person = UserFactory(profile__no_training_eligible=True)
    mine = ShiftFactory(starts_at=at(1, 9))
    booking.sign_up(person, mine)
    ShiftFactory(starts_at=at(1, 13))
    this_month = timezone.localdate().strftime("%Y-%m")
    html = page(client, person, "/my-shifts/?month=2020-01")
    assert f'href="?month={this_month}">Today</a>' in html
    html = page(client, person, "/my-shifts/")
    assert 'aria-current="date">Today</a>' in html and "calendar__today-word" in html
    # Tomorrow can be in next month, so look at the month the shift is in.
    html = page(client, person, f"/my-shifts/?month={mine.local_date:%Y-%m}")
    assert "cal-chip--mine" in html and "cal-chip--open" in html
    assert "your shift, 1 open shift" in html


def test_home_without_shifts_offers_find_a_shift(client):
    html = page(client, UserFactory())
    assert "have any upcoming shifts" in html
    assert '<a class="btn btn--primary" href="/shifts/">Find a shift</a>' in html


def test_next_shift_says_it_is_confirmed(client):
    person = UserFactory(profile__no_training_eligible=True)
    booking.sign_up(person, ShiftFactory(title="Dog walking"))
    html = page(client, person)
    assert "Your next shift" in html and "status--confirmed" in html


def test_pending_requests_say_plainly_that_they_are_waiting(client):
    person = UserFactory(profile__no_training_eligible=True, profile__needs_approval=True)
    booking.ask_to_join(person, ShiftFactory(title="Adoption event"))
    html = page(client, person)
    assert "Waiting for approval" in html
    assert "The volunteer team has not approved it yet." in html
    assert 'Status: <span class="status status--pending">Pending</span>' in html


def test_a_day_with_nothing_open_points_to_find_a_shift(client):
    day = (timezone.localdate() + timezone.timedelta(days=5)).isoformat()
    html = page(client, UserFactory(), f"/my-shifts/{day}/")
    assert "Nothing open on this day" in html and 'href="/shifts/">Find a shift</a>' in html


# Staff switching to the volunteer view and back


def test_staff_can_flip_to_the_volunteer_view_and_back(client):
    client.force_login(StaffFactory(first_name="Cindy"))
    html = client.get("/").content.decode()
    assert "See volunteer view" in html and "<h1>Dashboard</h1>" in html

    assert client.post("/switch-view/", {"to": "volunteer"})["Location"] == "/"
    html = client.get("/").content.decode()
    assert "<h1>Dashboard</h1>" not in html and ", Cindy</h1>" in html
    assert 'data-role="volunteer"' in html
    assert "in the volunteer view" in html and "Back to staff view" in html
    start = html.index('<nav class="site-nav')
    menu = html[start : html.index("</nav>", start)]
    assert ">Find a shift</a>" in menu and ">Admin</a>" not in menu
    # Still staff underneath: the badge says so, and staff pages still open.
    assert '<span class="role-badge role-badge--staff">Staff</span>' in html
    assert client.get("/schedule/").status_code == 200

    client.post("/switch-view/", {"to": "staff"})
    html = client.get("/").content.decode()
    assert "<h1>Dashboard</h1>" in html and "in the volunteer view" not in html


def test_volunteers_have_no_view_switch(client):
    client.force_login(UserFactory())
    assert "volunteer view" not in client.get("/").content.decode()
    assert client.post("/switch-view/", {"to": "volunteer"}).status_code == 403
