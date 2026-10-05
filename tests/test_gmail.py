"""Sending through Gmail's web API, and the one-time authorization. No test touches the network."""

import base64
import io
import json
import urllib.error
from email import message_from_bytes
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core import mail
from django.core.mail import EmailMessage
from django.core.management import CommandError, call_command

from core import errors
from insights.models import Problem
from notifications import gmail
from notifications.backends import GmailApiBackend
from notifications.email import send
from notifications.models import EmailLog
from tests.factories import StaffFactory, UserFactory
from tests.test_settings import _env, _run


class FakeGoogle:
    """Stands in for urlopen: records each request and answers from a queue."""

    def __init__(self):
        self.requests = []
        self.replies = []

    def reply(self, body, status=200):
        """Queue the next answer."""
        self.replies.append((status, body))

    def __call__(self, request, timeout=None):
        """Answer like urlopen: a readable reply, or an HTTPError for 4xx and 5xx."""
        self.requests.append(request)
        status, body = self.replies.pop(0) if self.replies else (200, {"access_token": "access-1"})
        data = json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "refused", {}, io.BytesIO(data))
        return io.BytesIO(data)


@pytest.fixture
def google(monkeypatch, settings):
    settings.GMAIL_CLIENT_ID = "client-id"
    settings.GMAIL_CLIENT_SECRET = "client-secret"
    settings.GMAIL_REFRESH_TOKEN = "refresh-token"
    fake = FakeGoogle()
    monkeypatch.setattr(gmail.urllib.request, "urlopen", fake)
    gmail.forget_token()
    yield fake
    gmail.forget_token()


def _message(to="mary@example.com"):
    return EmailMessage("Hello", "Your shift is tomorrow.", "shelter@example.com", [to])


def test_an_email_goes_to_gmail_over_https(google):
    google.reply({"access_token": "access-1", "expires_in": 3600})
    google.reply({"id": "sent"})
    assert GmailApiBackend().send_messages([_message()]) == 1
    token_request, send_request = google.requests
    assert token_request.full_url == gmail.TOKEN_URL
    assert parse_qs(token_request.data.decode())["grant_type"] == ["refresh_token"]
    assert send_request.full_url == gmail.SEND_URL
    assert send_request.get_header("Authorization") == "Bearer access-1"
    sent = message_from_bytes(base64.urlsafe_b64decode(json.loads(send_request.data)["raw"]))
    assert sent["To"] == "mary@example.com" and sent["Subject"] == "Hello"
    assert "Your shift is tomorrow." in sent.get_payload()


def test_the_access_token_is_reused_between_emails(google):
    GmailApiBackend().send_messages([_message(), _message("joe@example.com")])
    assert [r.full_url for r in google.requests] == [
        gmail.TOKEN_URL,
        gmail.SEND_URL,
        gmail.SEND_URL,
    ]


def test_a_stale_access_token_is_replaced_once(google):
    google.reply({"access_token": "old"})
    google.reply({"error": {"code": 401, "message": "Invalid Credentials"}}, status=401)
    google.reply({"access_token": "new"})
    google.reply({"id": "sent"})
    assert GmailApiBackend().send_messages([_message()]) == 1
    assert google.requests[-1].get_header("Authorization") == "Bearer new"


def test_a_revoked_authorization_says_what_to_do_without_leaking_secrets(google):
    google.reply({"error": "invalid_grant", "error_description": "Token has been revoked."}, 400)
    with pytest.raises(gmail.GmailError) as caught:
        GmailApiBackend().send_messages([_message()])
    message = str(caught.value)
    assert "gmail_authorize" in message
    assert "refresh-token" not in message and "client-secret" not in message


def test_gmail_refusing_a_message_gives_its_reason(google):
    google.reply({"access_token": "access-1"})
    google.reply({"error": {"code": 403, "message": "Daily sending limit reached"}}, status=403)
    with pytest.raises(gmail.GmailError, match="Daily sending limit reached"):
        GmailApiBackend().send_messages([_message()])
    google.reply({"error": {"code": 403, "message": "Daily sending limit reached"}}, status=403)
    assert GmailApiBackend(fail_silently=True).send_messages([_message()]) == 0


@pytest.mark.django_db
def test_a_gmail_failure_is_logged_and_reported_like_any_other(google, settings):
    settings.EMAIL_BACKEND = "notifications.backends.GmailApiBackend"
    google.reply({"error": "invalid_grant"}, status=400)
    person = UserFactory()
    log = send("request_approved", to=person.email, context={"person": person, "shift": "Dogs"})
    assert log.failed and "gmail_authorize" in log.error
    assert Problem.objects.get().code == errors.EMAIL_FAILED.code
    assert not mail.outbox


# Choosing how to send


@pytest.mark.parametrize(
    ("extra", "backend"),
    [
        ({}, "console.EmailBackend"),
        ({"EMAIL_HOST_USER": "a@example.com", "EMAIL_HOST_PASSWORD": "x"}, "smtp.EmailBackend"),
        (
            {
                "EMAIL_HOST_USER": "a@example.com",
                "EMAIL_HOST_PASSWORD": "x",
                "GMAIL_CLIENT_ID": "i",
                "GMAIL_CLIENT_SECRET": "s",
                "GMAIL_REFRESH_TOKEN": "r",
            },
            "notifications.backends.GmailApiBackend",
        ),
        ({"GMAIL_CLIENT_ID": "i", "GMAIL_CLIENT_SECRET": "s"}, "console.EmailBackend"),
    ],
)
def test_settings_pick_gmail_when_all_three_values_are_set(extra, backend):
    cleared = {
        key: ""
        for key in (
            "EMAIL_BACKEND",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REFRESH_TOKEN",
        )
    }
    env = _env(SECRET_KEY="x" * 60, **{**cleared, **extra})
    result = _run(["-c", "import config.settings as s; print(s.EMAIL_BACKEND)"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(backend)


# The one-time authorization


def test_the_sign_in_address_asks_only_to_send_and_for_a_lasting_token():
    url = gmail.authorization_url("client-id", "http://127.0.0.1:5000", "state-1", "verifier")
    query = parse_qs(urlsplit(url).query)
    assert url.startswith(gmail.AUTH_URL)
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.send"]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["code_challenge"] == [gmail.challenge_for("verifier")]
    assert query["redirect_uri"] == ["http://127.0.0.1:5000"]


def test_the_code_is_swapped_for_a_refresh_token(google):
    google.reply({"access_token": "a", "refresh_token": "refresh-123"})
    token = gmail.exchange_code("client-id", "client-secret", "code-1", "http://127.0.0.1:1", "v")
    assert token == "refresh-123"
    sent = parse_qs(google.requests[0].data.decode())
    assert sent["code"] == ["code-1"] and sent["code_verifier"] == ["v"]
    google.reply({"access_token": "a"})
    with pytest.raises(gmail.GmailError, match="refresh token"):
        gmail.exchange_code("client-id", "client-secret", "code-1", "http://127.0.0.1:1", "v")


class FakeServer:
    """Stands in for the local listener: answers as if Google had redirected back."""

    answer = None
    server_port = 51234

    def __init__(self, *args):
        self.timeout = None

    def handle_request(self):
        """Pretend the browser came back with this answer."""
        type(self).last = self
        self.answer = dict(type(self).will_answer)

    def server_close(self):
        """Nothing to close."""


@pytest.fixture
def authorize(monkeypatch, settings):
    from notifications.management.commands import gmail_authorize as command

    settings.GMAIL_CLIENT_ID = "client-id"
    settings.GMAIL_CLIENT_SECRET = "client-secret"
    monkeypatch.setattr(command, "HTTPServer", FakeServer)
    monkeypatch.setattr(command.secrets, "token_urlsafe", lambda n: "fixed")
    monkeypatch.setattr(gmail, "exchange_code", lambda *args: "refresh-123")

    def run(answer, *args):
        FakeServer.will_answer = answer
        out = io.StringIO()
        call_command("gmail_authorize", "--no-browser", *args, stdout=out)
        return out.getvalue()

    return run


def test_authorizing_prints_the_token_for_the_host(authorize):
    out = authorize({"code": ["code-1"], "state": ["fixed"]})
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A51234" in out
    assert "GMAIL_REFRESH_TOKEN=refresh-123" in out


def test_an_answer_that_is_not_ours_is_refused(authorize):
    with pytest.raises(CommandError, match="didn't authorize"):
        authorize({"code": ["code-1"], "state": ["someone-else"]})
    with pytest.raises(CommandError, match="access_denied"):
        authorize({"error": ["access_denied"], "state": ["fixed"]})


def test_authorizing_needs_the_client_values_first(settings):
    settings.GMAIL_CLIENT_ID = ""
    with pytest.raises(CommandError, match="GMAIL_CLIENT_ID"):
        call_command("gmail_authorize")


def test_authorizing_can_send_a_test_email(authorize, google):
    google.reply({"access_token": "access-1"})
    google.reply({"id": "sent"})
    out = authorize({"code": ["c"], "state": ["fixed"]}, "--send-test-to", "mike@example.com")
    assert "Test email sent to mike@example.com" in out
    assert parse_qs(google.requests[0].data.decode())["refresh_token"] == ["refresh-123"]


# What staff see when an email fails


@pytest.mark.django_db
def test_the_failed_email_notice_only_blames_the_address_when_it_is_the_address(client):
    staff, person = StaffFactory(), UserFactory()
    client.force_login(staff)
    EmailLog.objects.create(
        to=person.email, template_key="welcome", related_user=person, error="GmailError: down"
    )
    page = client.get(f"/volunteers/{person.pk}/").content.decode()
    assert "not with their address" in page and "Check the email address" not in page
    EmailLog.objects.create(
        to="", template_key="welcome", related_user=person, error="No email address on file"
    )
    page = client.get(f"/volunteers/{person.pk}/").content.decode()
    assert "Check the email address" in page
