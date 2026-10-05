"""One-time setup: let the app send email as its Gmail account (docs/setup.md, section 4).

Run on the Admin's PC. It opens Google's sign-in page, waits for the answer on this
computer only, and prints the refresh token to paste into the host's settings.
"""

import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError

from notifications import gmail

WAIT_SECONDS = 300
DONE_PAGE = (
    b"<!doctype html><title>All done</title>"
    b"<p style='font: 1.25rem sans-serif; margin: 3rem'>All done. You can close this tab "
    b"and go back to PowerShell.</p>"
)


class _Catcher(BaseHTTPRequestHandler):
    """Receives Google's redirect on this computer and keeps what it carried."""

    def do_GET(self):
        """Store the answer and show a short "all done" page."""
        self.server.answer = parse_qs(urlsplit(self.path).query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DONE_PAGE)

    def log_message(self, *args):
        """Keep the one-time code out of the terminal."""


class Command(BaseCommand):
    help = "Authorize sending as the app's Gmail account and print GMAIL_REFRESH_TOKEN."

    def add_arguments(self, parser):
        """--send-test-to checks it works before anything is changed on the host."""
        parser.add_argument("--send-test-to", help="Send a test email to this address.")
        parser.add_argument(
            "--no-browser", action="store_true", help="Just print the address to open."
        )

    def handle(self, *args, send_test_to, no_browser, **options):
        """Sign in with Google in the browser, then print the token for the host."""
        client_id, client_secret = settings.GMAIL_CLIENT_ID, settings.GMAIL_CLIENT_SECRET
        if not (client_id and client_secret):
            raise CommandError(
                "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in this window first "
                "(docs/setup.md, section 4)."
            )
        server = HTTPServer(("127.0.0.1", 0), _Catcher)
        server.timeout = WAIT_SECONDS
        server.answer = None
        redirect_uri = f"http://127.0.0.1:{server.server_port}"
        state, verifier = secrets.token_urlsafe(16), secrets.token_urlsafe(64)
        url = gmail.authorization_url(client_id, redirect_uri, state, verifier)

        self.stdout.write(
            "Sign in as the app's Gmail account and choose Allow. If Google says it hasn't "
            "verified the app, choose Advanced, then Go to the app.\n"
        )
        if no_browser or not webbrowser.open(url):
            self.stdout.write(f"Open this address in your browser:\n{url}\n")
        try:
            server.handle_request()
        finally:
            server.server_close()

        answer = server.answer or {}
        if answer.get("state", [""])[0] != state or "code" not in answer:
            problem = answer.get("error", ["no answer came back in time"])[0]
            raise CommandError(f"Google didn't authorize the app ({problem}). Please try again.")
        try:
            token = gmail.exchange_code(
                client_id, client_secret, answer["code"][0], redirect_uri, verifier
            )
            if send_test_to:
                self._send_test(token, send_test_to)
        except gmail.GmailError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("\nAuthorized."))
        self.stdout.write(
            "Add this to the host's environment (with GMAIL_CLIENT_ID and "
            "GMAIL_CLIENT_SECRET). Treat it like a password: don't share or commit it.\n"
        )
        self.stdout.write(f"GMAIL_REFRESH_TOKEN={token}")

    def _send_test(self, token, address):
        message = EmailMessage(
            "Test email from the volunteer schedule",
            "This is a test. If you can read it, the app can send email through Gmail.",
            settings.DEFAULT_FROM_EMAIL,
            [address],
        )
        gmail.forget_token()
        gmail.send_raw(message.message().as_bytes(linesep="\r\n"), refresh_token=token)
        gmail.forget_token()
        self.stdout.write(f"Test email sent to {address}.")
