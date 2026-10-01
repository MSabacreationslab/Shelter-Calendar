"""Email last month's summary to staff (Railway cron runs it on the 1st on the pilot)."""

from core.commands import ReportedCommand, parse_date_option
from reports.senders import send_monthly_summary


class Command(ReportedCommand):
    help = "Email last month's summary to the notify list."

    def add_arguments(self, parser):
        """--date to act as if it's another day; --again to resend a month already sent."""
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD).")
        parser.add_argument("--again", action="store_true", help="Send even if already sent.")

    def handle(self, *args, date=None, again=False, **options):
        """Report what happened in one line."""
        result = send_monthly_summary(parse_date_option(date), again=again)
        self.stdout.write(f"Sent to {result.sent}." if result.sent else result.reason)
