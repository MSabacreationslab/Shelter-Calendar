"""Sending through Gmail's web API (HTTPS), because hosts block the mail ports.

Render's free plan and Railway's Hobby plan both block SMTP, so the app sends as its
Gmail account over ordinary web requests instead. `gmail_authorize` (run once, on the
Admin's PC) gets the refresh token; the three GMAIL_* settings then let the app send.
Nothing here logs or returns a secret.
"""

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
# Only permission to send; the app can never read the mailbox.
SCOPE = "https://www.googleapis.com/auth/gmail.send"
TIMEOUT = 20
REAUTHORIZE = (
    "Google no longer accepts the saved authorization (it expires if the Gmail password "
    "changes or access is removed). Run gmail_authorize again and update GMAIL_REFRESH_TOKEN."
)

_cache = {"token": "", "expires": 0.0}
_lock = threading.Lock()


class GmailError(Exception):
    """Google refused or couldn't be reached. The message is safe to show the Admin."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    """True when all three GMAIL_* settings are present."""
    return bool(
        settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET and settings.GMAIL_REFRESH_TOKEN
    )


def _explain(exc: urllib.error.HTTPError) -> str:
    try:
        reply = json.loads(exc.read() or b"{}")
    except ValueError:
        reply = {}
    error = reply.get("error")
    if error == "invalid_grant":
        return REAUTHORIZE
    if isinstance(error, dict):  # the Gmail API's shape
        return f"Gmail refused ({exc.code}): {error.get('message', 'no reason given')}"
    detail = reply.get("error_description") or error or "no reason given"
    return f"Google refused ({exc.code}): {detail}"


def _post(url: str, *, data: bytes, headers: dict) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise GmailError(_explain(exc), status=exc.code) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GmailError(f"Couldn't reach Google: {getattr(exc, 'reason', exc)}") from None


def _form(fields: dict) -> tuple[bytes, dict]:
    body = urllib.parse.urlencode(fields).encode()
    return body, {"Content-Type": "application/x-www-form-urlencoded"}


def challenge_for(verifier: str) -> str:
    """The PKCE challenge Google checks the verifier against."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_url(client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    """Where the Admin signs in as the app's Gmail account and allows sending."""
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge_for(verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        # Always ask, so Google always hands back a refresh token.
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(query)}"


def exchange_code(client_id, client_secret, code, redirect_uri, verifier) -> str:
    """Swap the one-time code from the browser for a long-lived refresh token."""
    data, headers = _form(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    reply = _post(TOKEN_URL, data=data, headers=headers)
    token = reply.get("refresh_token")
    if not token:
        raise GmailError("Google didn't return a refresh token. Please run this again.")
    return token


def forget_token() -> None:
    """Drop the cached access token (after a 401, or between tests)."""
    with _lock:
        _cache.update(token="", expires=0.0)


def access_token(refresh_token: str | None = None) -> str:
    """A short-lived access token, fetched with the refresh token and reused until it's stale."""
    with _lock:
        if _cache["token"] and time.monotonic() < _cache["expires"]:
            return _cache["token"]
        data, headers = _form(
            {
                "client_id": settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "refresh_token": refresh_token or settings.GMAIL_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            }
        )
        reply = _post(TOKEN_URL, data=data, headers=headers)
        _cache["token"] = reply["access_token"]
        # A minute early, so a token never expires mid-send.
        _cache["expires"] = time.monotonic() + int(reply.get("expires_in", 3600)) - 60
        return _cache["token"]


def send_raw(message_bytes: bytes, refresh_token: str | None = None) -> None:
    """Hand one finished email to Gmail. Retries once if the access token had gone stale."""
    raw = base64.urlsafe_b64encode(message_bytes).decode()
    data = json.dumps({"raw": raw}).encode()
    for attempt in (1, 2):
        headers = {
            "Authorization": f"Bearer {access_token(refresh_token)}",
            "Content-Type": "application/json",
        }
        try:
            _post(SEND_URL, data=data, headers=headers)
            return
        except GmailError as exc:
            if exc.status == 401 and attempt == 1:
                forget_token()
                continue
            raise
