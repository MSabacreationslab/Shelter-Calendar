"""Email last month's summary to staff (Railway cron runs it on the 1st on the pilot)."""

from django.core.management.base import BaseCommand

from reports.management.commands.send_weekly_digest import _parse
from reports.senders import send_monthly_summary


class Command(BaseCommand):
    help = "Email last month's summary to the notify list."

    def add_arguments(self, parser):
        """--date to act as if it's another day; --again to resend a month already sent."""
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD).")
        parser.add_argument("--again", action="store_true", help="Send even if already sent.")

    def handle(self, *args, date=None, again=False, **options):
        """Report what happened in one line."""
        result = send_monthly_summary(_parse(date), again=again)
        self.stdout.write(f"Sent to {result.sent}." if result.sent else result.reason)
