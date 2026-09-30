"""Training types, what each volunteer still needs, and completed training (SPEC §5)."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class TrainingType(models.Model):
    """Something a volunteer can be trained in, such as Dog walking or Orientation."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_orientation = models.BooleanField(
        default=False, help_text="Completing orientation lets someone take no-training shifts."
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="training_type_name_ci_unique"),
            models.UniqueConstraint(
                fields=["is_orientation"],
                condition=models.Q(is_orientation=True),
                name="training_single_orientation",
            ),
        ]

    def __str__(self):
        return self.name


class TrainingNeed(models.Model):
    """A training staff want someone to complete; resolved when the record is saved."""

    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="training_needs"
    )
    training_type = models.ForeignKey(TrainingType, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["volunteer", "training_type"],
                condition=models.Q(resolved_at__isnull=True),
                name="training_one_open_need",
            ),
        ]

    def __str__(self):
        return f"{self.volunteer} needs {self.training_type}"


class TrainingRecord(models.Model):
    """Completed training. Mistakes are voided with a reason, never deleted."""

    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="training_records"
    )
    training_type = models.ForeignKey(TrainingType, on_delete=models.PROTECT, related_name="+")
    completed_on = models.DateField()
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    signed_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    session = models.ForeignKey(
        "scheduling.Shift",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="training_records",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-completed_on"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(voided_at__isnull=True)
                | (~models.Q(void_reason="") & models.Q(voided_by__isnull=False)),
                name="training_void_needs_reason",
            ),
        ]

    def __str__(self):
        return f"{self.volunteer}: {self.training_type} ({self.completed_on})"
