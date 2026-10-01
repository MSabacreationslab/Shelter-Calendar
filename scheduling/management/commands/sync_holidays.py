"""Fill in this year's and next year's US federal holidays (runs on every deploy)."""

from core.commands import ReportedCommand
from scheduling.holidays import sync_federal_holidays


class Command(ReportedCommand):
    help = "Add this year's and next year's federal holidays. Safe to run any number of times."

    def handle(self, *args, **options):
        """Idempotent: holidays already there are left alone, including hidden ones."""
        added = sync_federal_holidays()
        self.stdout.write(f"Added {added} holidays.")
