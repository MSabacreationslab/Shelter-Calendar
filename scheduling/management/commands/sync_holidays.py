"""Fill in this year's and next year's US federal holidays (runs on every deploy)."""

from django.core.management.base import BaseCommand

from scheduling.holidays import sync_federal_holidays


class Command(BaseCommand):
    help = "Add this year's and next year's federal holidays. Safe to run any number of times."

    def handle(self, *args, **options):
        """Idempotent: holidays already there are left alone, including hidden ones."""
        added = sync_federal_holidays()
        self.stdout.write(f"Added {added} holidays.")
