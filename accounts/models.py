"""People, their profiles, setup links and sign-in attempts (SPEC §4, §5)."""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


def normalize_login_name(name: str) -> str:
    """Trim a sign-in name and collapse runs of spaces, keeping its capitals."""
    return " ".join(name.split())


class Role(models.TextChoices):
    VOLUNTEER = "volunteer", "Volunteer"
    STAFF = "staff", "Staff"
    ADMIN = "admin", "Admin"


class Status(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class UserManager(BaseUserManager):
    """Creates people, with sign-in names normalized the same way sign-in matches them."""

    use_in_migrations = True

    def get_by_natural_key(self, login_name):
        """Find someone by sign-in name, ignoring capitals and extra spaces."""
        return self.get(login_name__iexact=normalize_login_name(login_name))

    def create_user(self, login_name, password=None, **extra_fields):
        """Create a person; without a PIN they can't sign in until they set one from a link."""
        if not login_name:
            raise ValueError("A sign-in name is required.")
        user = self.model(login_name=normalize_login_name(login_name), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, login_name, password=None, **extra_fields):
        """Create the Admin, who also has the Django admin backend."""
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(login_name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A person who signs in with their name and a PIN."""

    login_name = models.CharField("sign-in name", max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True, help_text="Digits only.")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VOLUNTEER)
    job_title = models.CharField(
        max_length=100, blank=True, help_text='Staff only, e.g. "Volunteer Lead".'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    avatar = models.CharField(max_length=30, blank=True, help_text="Blank shows initials.")
    # Access to the Django admin backend; only the Admin has it.
    is_staff = models.BooleanField(default=False)
    locked_until = models.DateTimeField(null=True, blank=True)
    pin_reset_required = models.BooleanField(
        default=False, help_text="Locked until staff send a new setup link."
    )
    date_joined = models.DateTimeField(default=timezone.now)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "login_name"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["last_name", "first_name", "login_name"]
        constraints = [
            models.UniqueConstraint(Lower("login_name"), name="accounts_user_login_name_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="accounts_user_role_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=Status.values), name="accounts_user_status_valid"
            ),
        ]

    def __str__(self):
        return self.get_full_name()

    @property
    def is_active(self):
        """Django's sign-in and admin checks follow the person's status."""
        return self.status == Status.ACTIVE

    @property
    def is_staff_member(self):
        """Staff or the Admin: can use the staff screens."""
        return self.role in (Role.STAFF, Role.ADMIN)

    @property
    def is_admin(self):
        """The Admin (Mike)."""
        return self.role == Role.ADMIN

    def get_full_name(self):
        """First and last name, or the sign-in name if those are blank."""
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.login_name

    def get_short_name(self):
        """First name, or the sign-in name if it's blank."""
        return self.first_name or self.login_name

    @property
    def initials(self):
        """Up to two initials for the avatar circle."""
        parts = [p for p in (self.first_name, self.last_name) if p] or self.login_name.split()
        return "".join(p[0].upper() for p in parts[:2])


class Skill(models.Model):
    """Something a volunteer does or is interested in. Informational only, never eligibility."""

    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="accounts_skill_name_ci_unique"),
        ]

    def __str__(self):
        return self.name


class VolunteerProfile(models.Model):
    """Details kept for each person who can take shifts."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)
    skills = models.ManyToManyField(Skill, blank=True, related_name="volunteers")
    birthday_month = models.PositiveSmallIntegerField(null=True, blank=True)
    birthday_day = models.PositiveSmallIntegerField(null=True, blank=True)
    no_training_eligible = models.BooleanField(
        default=False, help_text="May sign up for shifts that need no training."
    )
    staff_notes = models.TextField(blank=True)
    wants_reminders = models.BooleanField(
        default=True, help_text="Email reminders before their shifts (they can turn these off)."
    )
    is_minor = models.BooleanField(
        default=False, help_text="Under 18. Staff see it; it doesn't change what they can take."
    )
    needs_approval = models.BooleanField(
        default=False,
        help_text="Staff approve each shift they ask for. They can still sign in.",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(birthday_month__isnull=True, birthday_day__isnull=True)
                    | models.Q(
                        birthday_month__gte=1,
                        birthday_month__lte=12,
                        birthday_day__gte=1,
                        birthday_day__lte=31,
                    )
                ),
                name="accounts_profile_birthday_valid",
            ),
        ]

    def __str__(self):
        return f"Profile for {self.user}"


class SetupLinkPurpose(models.TextChoices):
    INVITE = "invite", "Welcome"
    RESET = "reset", "New PIN"


class SetupLink(models.Model):
    """A one-time link for choosing a PIN. Only a hash of the token is stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="setup_links"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=10, choices=SetupLinkPurpose.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_purpose_display()} link for {self.user}"

    def is_valid(self, now=None) -> bool:
        """Not used, not replaced by a newer link, and not expired."""
        now = now or timezone.now()
        return self.used_at is None and self.voided_at is None and self.expires_at > now


class LoginAttempt(models.Model):
    """One sign-in try, kept for lockouts and troubleshooting. Pruned after 90 days."""

    name_entered = models.CharField(max_length=150)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="login_attempts",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    succeeded = models.BooleanField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["ip", "created_at"]),
        ]

    def __str__(self):
        outcome = "ok" if self.succeeded else "failed"
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.name_entered} {outcome}"
