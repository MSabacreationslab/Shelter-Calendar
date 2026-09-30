"""Shifts, the patterns that generate them, sign-ups and the waitlist (SPEC §5).

The database enforces the booking invariants; services check first so they can
explain problems in plain words, and these constraints are the backstop.
"""

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

WAITLIST_MAX = 10


class ShiftKind(models.TextChoices):
    REGULAR = "regular", "Regular shift"
    TRAINING = "training", "Training session"


class ShiftStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    CANCELLED = "cancelled", "Cancelled"


def _kind_matches_teaches(prefix=""):
    """Training sessions say what they teach; regular shifts don't."""
    return models.Q(**{f"{prefix}kind": ShiftKind.TRAINING, f"{prefix}teaches__isnull": False}) | (
        models.Q(**{f"{prefix}kind": ShiftKind.REGULAR, f"{prefix}teaches__isnull": True})
    )


class TemplateWeek(models.Model):
    """A named set of weekly patterns, such as "Regular week" or "Summer"."""

    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="scheduling_template_name_ci_unique"),
        ]

    def __str__(self):
        return self.name


class ShiftPattern(models.Model):
    """A repeating shift: which weekday, what time, how many people, what training."""

    template_week = models.ForeignKey(
        TemplateWeek, null=True, blank=True, on_delete=models.PROTECT, related_name="patterns"
    )
    title = models.CharField(max_length=100)
    weekday = models.PositiveSmallIntegerField(help_text="0 = Monday … 6 = Sunday.")
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveSmallIntegerField(default=1)
    kind = models.CharField(max_length=10, choices=ShiftKind.choices, default=ShiftKind.REGULAR)
    required_training = models.ForeignKey(
        "training.TrainingType", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    teaches = models.ForeignKey(
        "training.TrainingType", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    every_n_weeks = models.PositiveSmallIntegerField(default=1)
    anchor_date = models.DateField(
        help_text="A date in a week this pattern runs, for every-other-week."
    )
    active_from = models.DateField()
    active_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0, weekday__lte=6), name="pattern_weekday_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="pattern_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1), name="pattern_capacity_min"
            ),
            models.CheckConstraint(
                condition=models.Q(every_n_weeks__in=[1, 2]), name="pattern_every_1_or_2_weeks"
            ),
            models.CheckConstraint(
                condition=models.Q(active_until__isnull=True)
                | models.Q(active_until__gte=models.F("active_from")),
                name="pattern_active_range_valid",
            ),
            models.CheckConstraint(condition=_kind_matches_teaches(), name="pattern_kind_teaches"),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_weekday_display()} {self.start_time:%H:%M})"

    def get_weekday_display(self):
        """The weekday's name."""
        return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
            self.weekday
        ]


class Shift(models.Model):
    """One shift on one day. Generated from a pattern or made by hand; always editable."""

    pattern = models.ForeignKey(
        ShiftPattern, null=True, blank=True, on_delete=models.SET_NULL, related_name="shifts"
    )
    title = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=ShiftKind.choices, default=ShiftKind.REGULAR)
    teaches = models.ForeignKey(
        "training.TrainingType", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    required_training = models.ForeignKey(
        "training.TrainingType", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    local_date = models.DateField(editable=False, help_text="The shelter-time date it starts on.")
    capacity = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=ShiftStatus.choices, default=ShiftStatus.SCHEDULED
    )
    cancel_reason = models.CharField(max_length=200, blank=True)
    holiday_name = models.CharField(max_length=100, blank=True)
    edited_by_hand = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["starts_at", "title"]
        indexes = [models.Index(fields=["local_date", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="shift_ends_after_start"
            ),
            models.CheckConstraint(condition=models.Q(capacity__gte=1), name="shift_capacity_min"),
            models.CheckConstraint(condition=_kind_matches_teaches(), name="shift_kind_teaches"),
            # Filling the schedule twice never makes a second copy of the same shift.
            models.UniqueConstraint(
                fields=["pattern", "local_date"],
                condition=models.Q(pattern__isnull=False),
                name="shift_one_per_pattern_per_day",
            ),
        ]

    def __str__(self):
        return f"{self.title} {timezone.localtime(self.starts_at):%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        """Keep the local date in step with the start time."""
        self.local_date = timezone.localtime(self.starts_at).date()
        super().save(*args, **kwargs)


class SignupStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Signed up"
    CANCELLED = "cancelled", "Cancelled"


class Signup(models.Model):
    """One person on one shift."""

    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="signups")
    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="signups"
    )
    status = models.CharField(
        max_length=10, choices=SignupStatus.choices, default=SignupStatus.CONFIRMED
    )
    # A copy of the shift's times, so the database itself can refuse overlapping shifts.
    period = DateTimeRangeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancel_reason = models.CharField(max_length=200, blank=True)
    is_late_cancel = models.BooleanField(default=False)
    # Decided when it happened, so changing the threshold later doesn't rewrite history.
    was_urgent = models.BooleanField(default=False)
    # Set from the welcome email's "this orientation time doesn't work" link.
    conflict_reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["shift__starts_at"]
        constraints = [
            # A double tap can't sign someone up twice.
            models.UniqueConstraint(
                fields=["shift", "volunteer"],
                condition=models.Q(status=SignupStatus.CONFIRMED),
                name="signup_once_per_shift",
            ),
            # Nobody can hold two overlapping shifts, even if two sign-ups race.
            ExclusionConstraint(
                name="signup_no_overlap",
                expressions=[
                    ("volunteer", RangeOperators.EQUAL),
                    ("period", RangeOperators.OVERLAPS),
                ],
                condition=models.Q(status=SignupStatus.CONFIRMED),
            ),
        ]

    def __str__(self):
        return f"{self.volunteer} on {self.shift}"


class WaitlistStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    PROMOTED = "promoted", "Moved onto the shift"
    LEFT = "left", "Left the waitlist"
    REMOVED = "removed", "Removed by staff"
    EXPIRED = "expired", "Shift passed"


class WaitlistEntry(models.Model):
    """Someone waiting for a spot on a full shift. Staff move people on by hand."""

    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="waitlist")
    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="waitlist_entries"
    )
    status = models.CharField(
        max_length=10, choices=WaitlistStatus.choices, default=WaitlistStatus.WAITING
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "waitlist entries"
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "volunteer"],
                condition=models.Q(status=WaitlistStatus.WAITING),
                name="waitlist_once_per_shift",
            ),
        ]

    def __str__(self):
        return f"{self.volunteer} waiting for {self.shift}"


class BlackoutPeriod(models.Model):
    """Days the shelter is closed; filling the schedule skips them."""

    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="blackout_range_valid",
            ),
        ]

    def __str__(self):
        return f"{self.reason} ({self.start_date} to {self.end_date})"


class HolidaySource(models.TextChoices):
    FEDERAL = "federal", "US federal holiday"
    SHELTER = "shelter", "Shelter holiday"


class Holiday(models.Model):
    """A flagged day. Federal ones are filled in automatically; staff add or hide others."""

    date = models.DateField()
    name = models.CharField(max_length=100)
    source = models.CharField(max_length=10, choices=HolidaySource.choices)
    hidden = models.BooleanField(default=False, help_text="Hidden holidays aren't flagged.")

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["date", "name"], name="holiday_unique_per_day"),
        ]

    def __str__(self):
        return f"{self.name} ({self.date})"
