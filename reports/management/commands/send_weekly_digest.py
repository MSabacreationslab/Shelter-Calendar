"""Email next week's schedule to staff (Railway cron runs it Sundays at 6 PM on the pilot)."""

from core.commands import ReportedCommand, parse_date_option
from reports.senders import send_weekly_digest


class Command(ReportedCommand):
    help = "Email the Sunday digest (next week's schedule) to the notify list."

    def add_arguments(self, parser):
        """--date to act as if it's another day; --again to resend a week already sent."""
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD).")
        parser.add_argument("--again", action="store_true", help="Send even if already sent.")

    def handle(self, *args, date=None, again=False, **options):
        """Report what happened in one line."""
        result = send_weekly_digest(parse_date_option(date), again=again)
        self.stdout.write(f"Sent to {result.sent}." if result.sent else result.reason)
