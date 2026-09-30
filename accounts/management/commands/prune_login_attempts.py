"""Delete sign-in attempts older than 90 days (they're only kept for lockouts and support)."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import LoginAttempt

KEEP_FOR = timedelta(days=90)


class Command(BaseCommand):
    help = "Delete sign-in attempts older than 90 days."

    def handle(self, *args, **options):
        """Run daily (Railway cron on the pilot)."""
        deleted, _ = LoginAttempt.objects.filter(created_at__lt=timezone.now() - KEEP_FOR).delete()
        self.stdout.write(f"Deleted {deleted} old sign-in attempts.")
