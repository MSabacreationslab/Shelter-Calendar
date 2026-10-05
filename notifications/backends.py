"""Django email backend that sends through Gmail's web API (see notifications/gmail.py)."""

from django.core.mail.backends.base import BaseEmailBackend

from notifications import gmail


class GmailApiBackend(BaseEmailBackend):
    """Used automatically when the three GMAIL_* settings are present."""

    def send_messages(self, email_messages):
        """Send each message as the app's Gmail account; returns how many went."""
        sent = 0
        for message in email_messages or []:
            if not message.recipients():
                continue
            try:
                gmail.send_raw(message.message().as_bytes(linesep="\r\n"))
            except Exception:
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent
