"""Sign-in, lockouts and setup links (SPEC §4). Views stay thin and call these."""

import enum
import hashlib
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    LoginAttempt,
    Role,
    SetupLink,
    User,
    VolunteerProfile,
    normalize_login_name,
)
from core import audit
from core.models import AuditEvent

FAILURE_WINDOW = timedelta(minutes=15)
FAILURES_BEFORE_LOCK = 5
LOCK_LENGTH = timedelta(minutes=15)
LOCKOUTS_BEFORE_NEW_LINK = 3
LOCKOUT_MEMORY = timedelta(hours=24)
DEVICE_FAILURE_LIMIT = 20
FORGOT_HINT_AFTER = 3
SETUP_LINK_LIFETIME = timedelta(days=7)
SESSION_LENGTH = {
    Role.VOLUNTEER: timedelta(days=30),
    # Staff can see everyone's contact details, so their sign-in lasts a working day.
    Role.STAFF: timedelta(hours=12),
    Role.ADMIN: timedelta(hours=12),
}


class Outcome(enum.Enum):
    SIGNED_IN = "signed_in"
    WRONG = "wrong"
    LOCKED = "locked"
    NEEDS_NEW_LINK = "needs_new_link"
    DEVICE_BLOCKED = "device_blocked"
    TURNED_OFF = "turned_off"


@dataclass
class SignInResult:
    outcome: Outcome
    user: User | None = None
    show_forgot_hint: bool = False


def client_ip(request) -> str | None:
    """The visitor's address, trusting only the proxies we run behind (TRUSTED_PROXY_COUNT)."""
    candidate = request.META.get("REMOTE_ADDR", "")
    count = settings.TRUSTED_PROXY_COUNT
    if count > 0:
        forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
        forwarded = [p for p in forwarded if p]
        # Each trusted proxy appends the address it received the request from, so the
        # entry `count` places from the end is the one no client could have forged.
        if len(forwarded) >= count:
            candidate = forwarded[-count]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _record_attempt(name, user, ip, succeeded, now):
    LoginAttempt.objects.create(
        name_entered=name[:150], user=user, ip=ip, succeeded=succeeded, created_at=now
    )


def _device_blocked(ip, now) -> bool:
    if ip is None:
        return False
    recent = LoginAttempt.objects.filter(
        ip=ip, succeeded=False, created_at__gt=now - FAILURE_WINDOW
    ).count()
    return recent >= DEVICE_FAILURE_LIMIT


def _name_failures_from_device(name, ip, now) -> int:
    """Recent misses for this name from this device, counted the same whether or not it exists."""
    return LoginAttempt.objects.filter(
        name_entered=name, ip=ip, succeeded=False, created_at__gt=now - FAILURE_WINDOW
    ).count()


def _account_failures(user, now) -> int:
    """Misses since the later of: 15 minutes ago, the last lock ending, the last success."""
    window_start = now - FAILURE_WINDOW
    if user.locked_until and user.locked_until <= now:
        window_start = max(window_start, user.locked_until)
    last_ok = (
        LoginAttempt.objects.filter(user=user, succeeded=True)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if last_ok:
        window_start = max(window_start, last_ok)
    return LoginAttempt.objects.filter(
        user=user, succeeded=False, created_at__gt=window_start
    ).count()


def _lock(user, now) -> Outcome:
    """Lock the account for 15 minutes; the third lock in a day needs a new setup link."""
    user.locked_until = now + LOCK_LENGTH
    audit.record("account.locked_out", target_user=user, at=now)
    lockouts_today = AuditEvent.objects.filter(
        action="account.locked_out", target_user=user, created_at__gt=now - LOCKOUT_MEMORY
    ).count()
    if lockouts_today >= LOCKOUTS_BEFORE_NEW_LINK:
        user.pin_reset_required = True
        audit.record("account.needs_new_link", target_user=user, at=now)
    user.save(update_fields=["locked_until", "pin_reset_required"])
    return Outcome.NEEDS_NEW_LINK if user.pin_reset_required else Outcome.LOCKED


@transaction.atomic
def sign_in(request, name: str, pin: str, now=None) -> SignInResult:
    """Check a name and PIN, applying every lockout rule, and sign the person in if right."""
    now = now or timezone.now()
    name = normalize_login_name(name)
    ip = client_ip(request)

    # Blocked tries aren't recorded: no PIN was checked, and recording them would
    # keep extending the wait for someone who stopped.
    if _device_blocked(ip, now):
        return SignInResult(Outcome.DEVICE_BLOCKED)

    user = User.objects.select_for_update().filter(login_name__iexact=name).first()
    if user is None:
        make_password(pin)  # Same work as a real check, so timing doesn't reveal names.
        _record_attempt(name, None, ip, False, now)
        misses = _name_failures_from_device(name, ip, now)
        # Unknown names "lock" like real ones, so lockouts don't reveal who has an account.
        if misses >= FAILURES_BEFORE_LOCK:
            return SignInResult(Outcome.LOCKED)
        return SignInResult(Outcome.WRONG, show_forgot_hint=misses >= FORGOT_HINT_AFTER)

    if user.pin_reset_required:
        return SignInResult(Outcome.NEEDS_NEW_LINK, user)
    if user.locked_until and user.locked_until > now:
        return SignInResult(Outcome.LOCKED, user)

    if not user.check_password(pin):
        _record_attempt(name, user, ip, False, now)
        if _account_failures(user, now) >= FAILURES_BEFORE_LOCK:
            return SignInResult(_lock(user, now), user)
        misses = _name_failures_from_device(name, ip, now)
        return SignInResult(Outcome.WRONG, user, show_forgot_hint=misses >= FORGOT_HINT_AFTER)

    if not user.is_active:
        return SignInResult(Outcome.TURNED_OFF, user)

    _record_attempt(name, user, ip, True, now)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(int(SESSION_LENGTH[user.role].total_seconds()))
    if user.locked_until:
        user.locked_until = None
        user.save(update_fields=["locked_until"])
    return SignInResult(Outcome.SIGNED_IN, user)


def hash_token(token: str) -> str:
    """The stored form of a setup-link token."""
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def create_setup_link(user, *, purpose, created_by=None, now=None) -> str:
    """Make a new one-time link (voiding older unused ones) and return its raw token."""
    now = now or timezone.now()
    SetupLink.objects.filter(user=user, used_at__isnull=True, voided_at__isnull=True).update(
        voided_at=now
    )
    token = secrets.token_urlsafe(32)
    SetupLink.objects.create(
        user=user,
        token_hash=hash_token(token),
        purpose=purpose,
        created_by=created_by,
        created_at=now,
        expires_at=now + SETUP_LINK_LIFETIME,
    )
    audit.record("setup_link.sent", actor=created_by, target_user=user, at=now, purpose=purpose)
    return token


def setup_link_url(token: str) -> str:
    """The full address to put in an email or print."""
    return settings.SITE_URL.rstrip("/") + reverse("accounts:setup_pin", args=[token])


def find_valid_link(token: str, now=None) -> SetupLink | None:
    """The link for this token if it can still be used. Looking never uses it up."""
    link = SetupLink.objects.select_related("user").filter(token_hash=hash_token(token)).first()
    if link and link.is_valid(now) and link.user.is_active:
        return link
    return None


@transaction.atomic
def set_pin_from_link(token: str, pin: str, now=None) -> User | None:
    """Set the PIN, use up the link and clear any lock. None if the link stopped being valid."""
    now = now or timezone.now()
    link = (
        SetupLink.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=hash_token(token))
        .first()
    )
    if link is None or not link.is_valid(now) or not link.user.is_active:
        return None
    user = link.user
    user.set_password(pin)
    user.locked_until = None
    user.pin_reset_required = False
    user.save(update_fields=["password", "locked_until", "pin_reset_required"])
    link.used_at = now
    link.save(update_fields=["used_at"])
    SetupLink.objects.filter(user=user, used_at__isnull=True, voided_at__isnull=True).update(
        voided_at=now
    )
    audit.record("account.pin_set", actor=user, target_user=user, at=now)
    return user


def sign_in_after_setup(request, user):
    """Sign someone straight in after they choose their PIN."""
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(int(SESSION_LENGTH[user.role].total_seconds()))


@transaction.atomic
def create_person(
    *,
    first_name,
    last_name,
    email,
    role=Role.VOLUNTEER,
    login_name=None,
    created_by=None,
    **fields,
) -> User:
    """Add a person with a profile. They can't sign in until they set a PIN from a link."""
    is_admin = role == Role.ADMIN
    user = User.objects.create_user(
        login_name or f"{first_name} {last_name}",
        first_name=first_name,
        last_name=last_name,
        email=email,
        role=role,
        is_staff=is_admin,
        is_superuser=is_admin,
        **fields,
    )
    VolunteerProfile.objects.create(user=user, added_by=created_by)
    audit.record("account.created", actor=created_by, target_user=user, role=role)
    return user
