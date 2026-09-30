"""A record of every email, so "did it go out?" never needs the server logs."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailLog(models.Model):
    """One email the app tried to send, and whether it went out."""

    to = models.EmailField()
    template_key = models.CharField(max_length=50)
    subject = models.CharField(max_length=200)
    related_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="email_logs",
    )
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.template_key} to {self.to}"

    @property
    def failed(self) -> bool:
        """True if sending didn't work."""
        return self.sent_at is None


class ReminderKind(models.TextChoices):
    EVENING = "evening", "Evening-before reminder"
    WEEK = "week", "Sunday list of the week's shifts"
    BIRTHDAY = "birthday", "Birthday email"


class SentReminder(models.Model):
    """One reminder to one person for one date. A second run for the same date sends nothing."""

    kind = models.CharField(max_length=10, choices=ReminderKind.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_reminders"
    )
    for_date = models.DateField(help_text="The shift day, the Monday of the week, or the birthday.")
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "user", "for_date"], name="reminder_once_per_person_per_date"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.user} ({self.for_date})"
