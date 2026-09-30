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
