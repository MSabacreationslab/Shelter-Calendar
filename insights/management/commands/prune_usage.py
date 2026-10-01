"""Delete old page visits (90 days) and problems (a year). Run daily (Railway cron on the pilot)."""

from datetime import timedelta

from django.utils import timezone

from core.commands import ReportedCommand
from insights.models import PageView, Problem

KEEP_VISITS = timedelta(days=90)
KEEP_PROBLEMS = timedelta(days=365)


class Command(ReportedCommand):
    help = "Delete page visits older than 90 days and problems older than a year."

    def handle(self, *args, **options):
        """Prune both tables and say how many rows went."""
        now = timezone.now()
        visits, _ = PageView.objects.filter(at__lt=now - KEEP_VISITS).delete()
        problems, _ = Problem.objects.filter(at__lt=now - KEEP_PROBLEMS).delete()
        self.stdout.write(f"Deleted {visits} old page visits and {problems} old problems.")
