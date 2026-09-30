"""Every page is checked against every role (SPEC §3). New pages can't slip through."""

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from accounts.models import Role
from accounts.permissions import (
    ADMIN,
    ALL_CAPABILITIES,
    PUBLIC,
    ROLE_CAPABILITIES,
    SIGNED_IN,
    STAFF,
    VOLUNTEER,
    has_capability,
    requires,
)
from accounts.templatetags.capabilities import can
from tests.factories import AdminFactory, StaffFactory, UserFactory

# Stand-in values for URL parameters; the permission check runs before any lookup.
SAMPLE_ARGS = {
    "token": "not-a-real-token",
    "pk": "999999",
    "signup_pk": "999999",
    "entry_pk": "999999",
    "date": "2026-10-06",
    "day": "2026-10-06",
    "table": "people",
}
BACKEND_PREFIX = "django-admin/"


def _walk(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            route = prefix + str(entry.pattern)
            if route.startswith(BACKEND_PREFIX):
                continue
            yield from _walk(entry.url_patterns, route)
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.callback


def _app_urls():
    """(path, capability) for every page in the app except the Django admin backend."""
    urls = []
    for route, callback in _walk(get_resolver().url_patterns):
        if route.startswith(BACKEND_PREFIX):
            continue
        path = "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: SAMPLE_ARGS[m.group(1)], route)
        urls.append((path, getattr(callback, "required_capability", None)))
    return urls


def test_every_page_declares_what_it_needs():
    missing = [path for path, capability in _app_urls() if capability is None]
    assert not missing, f"Add @requires(...) to the views for: {missing}"


def _allowed(response):
    denied = response.status_code == 403
    sent_to_sign_in = response.status_code == 302 and response["Location"].startswith("/sign-in/?")
    return not denied and not sent_to_sign_in


PEOPLE = {
    "signed out": None,
    "volunteer": UserFactory,
    "staff": StaffFactory,
    "admin": AdminFactory,
}
ROLE_OF = {"volunteer": Role.VOLUNTEER, "staff": Role.STAFF, "admin": Role.ADMIN}


@pytest.mark.django_db
@pytest.mark.parametrize("who", list(PEOPLE))
def test_each_page_allows_exactly_the_right_people(client, who):
    factory = PEOPLE[who]
    if factory:
        client.force_login(factory())
    wrong = []
    for path, capability in _app_urls():
        response = client.get(path)
        if capability == PUBLIC:
            expected = True
        elif who == "signed out":
            expected = False
        elif capability == SIGNED_IN:
            expected = True
        else:
            expected = capability in ROLE_CAPABILITIES[ROLE_OF[who]]
        if _allowed(response) != expected:
            wrong.append((path, capability, response.status_code))
    assert not wrong


@pytest.mark.django_db
def test_backend_is_for_the_admin_only(client):
    assert client.get("/django-admin/", follow=True).redirect_chain[-1][0].startswith("/sign-in/")
    for factory in (UserFactory, StaffFactory):
        client.force_login(factory())
        response = client.get("/django-admin/", follow=True)
        assert response.redirect_chain[-1][0] == "/"
    client.force_login(AdminFactory())
    assert client.get("/django-admin/").status_code == 200


def test_capability_tiers_nest():
    assert VOLUNTEER < STAFF < ADMIN == ALL_CAPABILITIES
    assert ADMIN - STAFF == {"edit_settings"}


@pytest.mark.django_db
def test_turned_off_people_have_no_capabilities():
    person = StaffFactory(status="inactive")
    assert not has_capability(person, "view_dashboard")


@pytest.mark.django_db
def test_template_filter_follows_the_map():
    volunteer, staff = UserFactory(), StaffFactory()
    assert can(staff, "view_dashboard") and not can(volunteer, "view_dashboard")


def test_typos_in_capability_names_fail_loudly():
    with pytest.raises(ValueError):
        requires("view_dashbord")
    with pytest.raises(ValueError):
        has_capability(None, "view_dashbord")
