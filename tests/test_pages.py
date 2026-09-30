import re

import pytest
from django.test import Client
from django.utils.html import escape

from core import errors


def test_home_page_renders_with_shelter_name_and_one_heading(client):
    response = client.get("/")
    html = response.content.decode()
    assert response.status_code == 200
    assert "Humane Society of Madison County" in html
    assert len(re.findall(r"<h1[ >]", html)) == 1
    assert 'href="#main"' in html


def test_footer_shows_phone_as_a_dialable_link_when_set(client, settings):
    settings.SHELTER_PHONE = "(740) 555-0100"
    html = client.get("/").content.decode()
    assert 'href="tel:7405550100"' in html
    assert "(740) 555-0100" in html


def test_footer_without_phone_points_to_volunteer_team(client, settings):
    settings.SHELTER_PHONE = ""
    html = client.get("/").content.decode()
    assert "tel:" not in html
    assert "volunteer team" in html


def test_healthz_is_ok_and_skips_https_redirect(client, settings):
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/").status_code == 301


def test_every_response_carries_a_request_reference(client):
    ref = client.get("/").headers["X-Request-Ref"]
    assert re.fullmatch(r"[A-Z2-9]{6}", ref)


def test_styleguide_hidden_unless_debug_or_demo_mode(client, settings):
    settings.DEBUG = False
    settings.DEMO_MODE = False
    assert client.get("/styleguide/").status_code == 404
    settings.DEMO_MODE = True
    assert client.get("/styleguide/").status_code == 200


def test_styleguide_form_shows_plain_errors_linked_to_the_field(client, settings):
    settings.DEMO_MODE = True
    html = client.post("/styleguide/", {"name": "Mary", "phone": "123"}).content.decode()
    assert "Please enter a 10-digit phone number." in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="id_phone_hint id_phone_error"' in html


@pytest.mark.urls("tests.urls")
@pytest.mark.parametrize(
    ("path", "status", "error"),
    [
        ("/test/bad/", 400, errors.BAD_REQUEST),
        ("/test/forbidden/", 403, errors.NOT_ALLOWED),
        ("/no-such-page/", 404, errors.PAGE_NOT_FOUND),
        ("/test/boom/", 500, errors.SERVER_ERROR),
    ],
)
def test_error_pages_show_code_and_reference(path, status, error, settings):
    settings.DEBUG = False
    client = Client(raise_request_exception=False)
    response = client.get(path)
    html = response.content.decode()
    assert response.status_code == status
    assert error.code in html
    assert escape(error.title) in html
    assert response.headers["X-Request-Ref"] in html


@pytest.mark.urls("tests.urls")
def test_expired_form_shows_friendly_page():
    client = Client(enforce_csrf_checks=True)
    response = client.post("/test/form/", {})
    html = response.content.decode()
    assert response.status_code == 403
    assert errors.FORM_EXPIRED.code in html
    assert "open too long" in html


@pytest.mark.urls("tests.urls")
@pytest.mark.parametrize(
    ("path", "level"), [("/test/boom/", "ERROR"), ("/no-such-page/", "WARNING")]
)
def test_failures_are_logged_with_the_same_reference(path, level, caplog, settings):
    settings.DEBUG = False
    client = Client(raise_request_exception=False)
    response = client.get(path)
    ref = response.headers["X-Request-Ref"]
    records = [r for r in caplog.records if r.levelname == level]
    assert records
    assert all(r.ref == ref for r in records)
