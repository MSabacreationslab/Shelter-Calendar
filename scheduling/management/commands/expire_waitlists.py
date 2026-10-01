"""Close waitlist entries and unanswered requests for shifts that have started (daily)."""

from core.commands import ReportedCommand
from scheduling.services import close_past_requests, expire_past_waitlists


class Command(ReportedCommand):
    help = "Close waitlist entries and unanswered requests for shifts that have started."

    def handle(self, *args, **options):
        """Runs daily (Railway cron on the pilot)."""
        self.stdout.write(f"Closed {expire_past_waitlists()} waitlist entries.")
        self.stdout.write(f"Closed {close_past_requests()} unanswered requests.")
