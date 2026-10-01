"""The evening reminder run (Railway cron runs it daily at 6 PM on the pilot)."""

from django.utils import timezone

from core.commands import ReportedCommand, parse_date_option
from notifications.reminders import send_reminders


class Command(ReportedCommand):
    help = "Email tomorrow's shift reminders (and on Sundays, next week's lists)."

    def add_arguments(self, parser):
        """--date to act as if it's another day."""
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD).")

    def handle(self, *args, date=None, **options):
        """Report how many went out."""
        lists, evening = send_reminders(parse_date_option(date) or timezone.localdate())
        self.stdout.write(f"Sent {lists} weekly lists and {evening} reminders for tomorrow.")
