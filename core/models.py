"""Shelter-wide settings and the change log."""

from django.conf import settings
from django.db import IntegrityError, models
from django.utils import timezone


class ShelterSettings(models.Model):
    """The single row of settings the Admin can change (SPEC §5)."""

    shelter_name = models.CharField(max_length=200)
    shelter_phone = models.CharField(max_length=30, blank=True)
    shelter_email = models.EmailField(blank=True)
    self_cancel_hours = models.PositiveSmallIntegerField(
        default=24, help_text="Volunteers can cancel on their own until this many hours before."
    )
    # 72 hours during testing, at the shelter's request, so staff get more notice.
    urgent_threshold_hours = models.PositiveSmallIntegerField(
        default=72,
        choices=[(24, "24 hours"), (48, "48 hours"), (72, "72 hours")],
        help_text="A cancellation this close to the shift is urgent.",
    )
    notify_emails = models.TextField(
        blank=True, help_text="Staff who get notification emails, one address per line."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "shelter settings"
        verbose_name_plural = "shelter settings"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="core_settings_single_row"),
        ]

    def __str__(self):
        return "Shelter settings"

    @classmethod
    def load(cls) -> "ShelterSettings":
        """Return the settings row, creating it from the environment defaults the first time."""
        try:
            return cls.objects.get(pk=1)
        except cls.DoesNotExist:
            try:
                return cls.objects.create(
                    pk=1,
                    shelter_name=settings.SHELTER_NAME,
                    shelter_phone=settings.SHELTER_PHONE,
                    shelter_email=settings.SHELTER_EMAIL,
                )
            except IntegrityError:
                # Another request created it at the same moment.
                return cls.objects.get(pk=1)

    @property
    def notify_email_list(self) -> list[str]:
        """The notification addresses as a list."""
        return [line.strip() for line in self.notify_emails.splitlines() if line.strip()]


class AuditEvent(models.Model):
    """One entry in the change log. Entries are never edited or deleted (SPEC §3)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Who made the change; empty when the app did it automatically.",
    )
    action = models.CharField(max_length=60)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    target_repr = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_user", "created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args, **kwargs):
        """Allow creating an entry, never changing one."""
        if self.pk is not None:
            raise ValueError("Change-log entries can't be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Change-log entries are permanent."""
        raise ValueError("Change-log entries can't be deleted.")
