"""A record of which scheduled report emails went out, so none is sent twice."""

from django.db import models
from django.utils import timezone


class ReportKind(models.TextChoices):
    WEEKLY = "weekly", "Sunday digest"
    MONTHLY = "monthly", "Monthly summary"


class SentReport(models.Model):
    """One scheduled report for one period. A second trigger for the same period does nothing."""

    kind = models.CharField(max_length=10, choices=ReportKind.choices)
    period_start = models.DateField(help_text="The Monday of the week, or the 1st of the month.")
    sent_at = models.DateTimeField(default=timezone.now)
    recipients = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "period_start"], name="report_once_per_period"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.period_start}"
