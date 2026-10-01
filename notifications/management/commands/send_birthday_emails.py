"""The morning birthday run (Railway cron runs it daily at 8 AM on the pilot)."""

from django.utils import timezone

from core.commands import ReportedCommand, parse_date_option
from notifications.reminders import send_birthdays


class Command(ReportedCommand):
    help = "Email a happy-birthday thank-you to everyone whose birthday is today."

    def add_arguments(self, parser):
        """--date to act as if it's another day."""
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD).")

    def handle(self, *args, date=None, **options):
        """Report how many went out."""
        sent = send_birthdays(parse_date_option(date) or timezone.localdate())
        self.stdout.write(f"Sent {sent} birthday emails.")
