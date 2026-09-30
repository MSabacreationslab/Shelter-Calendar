"""People who use the app. Phase 1 adds roles, status, phone and the profile."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


def normalize_login_name(name: str) -> str:
    """Trim a sign-in name and collapse runs of spaces, keeping its capitals."""
    return " ".join(name.split())


class UserManager(BaseUserManager):
    """Creates people, with sign-in names normalized the same way sign-in matches them."""

    use_in_migrations = True

    def create_user(self, login_name, password=None, **extra_fields):
        """Create a person; without a password they can't sign in until they set a PIN."""
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
        """Create the backend superuser (the Admin's emergency access)."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(login_name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A person who signs in with their name and a PIN."""

    login_name = models.CharField("sign-in name", max_length=150, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    # Access to the Django admin backend only; app roles arrive in Phase 1.
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "login_name"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("login_name"), name="accounts_user_login_name_ci_unique"),
        ]

    def __str__(self):
        return self.login_name

    def get_full_name(self):
        """First and last name, or the sign-in name if those are blank."""
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.login_name

    def get_short_name(self):
        """First name, or the sign-in name if it's blank."""
        return self.first_name or self.login_name
