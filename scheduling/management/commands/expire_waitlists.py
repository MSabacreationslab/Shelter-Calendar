"""Close waitlist entries for shifts that have started (run daily)."""

from django.core.management.base import BaseCommand

from scheduling.services import expire_past_waitlists


class Command(BaseCommand):
    help = "Close waitlist entries for shifts that have already started."

    def handle(self, *args, **options):
        """Runs daily (Railway cron on the pilot)."""
        self.stdout.write(f"Closed {expire_past_waitlists()} waitlist entries.")
