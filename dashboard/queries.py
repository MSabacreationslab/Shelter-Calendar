"""What the staff dashboard shows (SPEC §6, Phase 6). Each function is one section."""

from datetime import timedelta

from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone

from accounts.models import SetupLink, Status, User
from scheduling.models import Shift, ShiftStatus, Signup, SignupStatus, WaitlistStatus

RECENT = timedelta(days=7)
SOON = timedelta(days=7)
LIST_LIMIT = 10


def _with_counts(shifts):
    return shifts.annotate(
        filled=Count("signups", filter=Q(signups__status=SignupStatus.CONFIRMED), distinct=True),
        waiting=Count("waitlist", filter=Q(waitlist__status=WaitlistStatus.WAITING), distinct=True),
    )


def today(now=None):
    """Today's shifts in time order, each with the people on it."""
    now = now or timezone.now()
    shifts = list(
        _with_counts(Shift.objects.filter(local_date=timezone.localdate(now)))
        .select_related("required_training", "teaches")
        .order_by("starts_at")
    )
    people = {}
    for signup in Signup.objects.filter(
        shift__in=shifts, status=SignupStatus.CONFIRMED
    ).select_related("volunteer"):
        people.setdefault(signup.shift_id, []).append(signup.volunteer)
    for shift in shifts:
        shift.people = sorted(people.get(shift.pk, []), key=lambda p: p.get_full_name())
        shift.open_spots = max(shift.capacity - shift.filled, 0)
    return shifts


def cancellations(now=None):
    """Volunteers' cancellations in the last week for shifts still to come (urgent first)."""
    now = now or timezone.now()
    return list(
        Signup.objects.filter(
            status=SignupStatus.CANCELLED,
            cancelled_at__gte=now - RECENT,
            shift__ends_at__gt=now,
            shift__status=ShiftStatus.SCHEDULED,
            cancelled_by=F("volunteer"),
        )
        .select_related("shift", "volunteer")
        .order_by("-was_urgent", "shift__starts_at")
    )


def short_shifts(now=None):
    """Shifts in the next 7 days that still have open spots, soonest first."""
    now = now or timezone.now()
    shifts = (
        _with_counts(
            Shift.objects.filter(
                status=ShiftStatus.SCHEDULED, starts_at__gt=now, starts_at__lte=now + SOON
            )
        )
        .filter(filled__lt=F("capacity"))
        .order_by("starts_at")
    )
    return shifts.count(), list(shifts[:LIST_LIMIT])


def waitlists_with_space(now=None):
    """Full-until-recently shifts where someone is waiting and a spot has opened."""
    now = now or timezone.now()
    return list(
        _with_counts(Shift.objects.filter(status=ShiftStatus.SCHEDULED, starts_at__gt=now))
        .filter(waiting__gt=0, filled__lt=F("capacity"))
        .order_by("starts_at")
    )


def orientation_conflicts(now=None):
    """New volunteers who said their orientation time doesn't work, still booked on it."""
    now = now or timezone.now()
    return list(
        Signup.objects.filter(
            conflict_reported_at__isnull=False,
            status=SignupStatus.CONFIRMED,
            shift__starts_at__gt=now,
        )
        .select_related("shift", "volunteer")
        .order_by("shift__starts_at")
    )


def expired_links(now=None):
    """People who never chose a PIN and whose last link has run out."""
    now = now or timezone.now()
    latest = SetupLink.objects.filter(user=OuterRef("pk")).order_by("-created_at")
    people = (
        User.objects.filter(status=Status.ACTIVE)
        .annotate(
            link_expires=Subquery(latest.values("expires_at")[:1]),
            link_used=Subquery(latest.values("used_at")[:1]),
        )
        .filter(link_expires__lte=now, link_used__isnull=True)
        .order_by("first_name", "last_name")
    )
    return [p for p in people if not p.has_usable_password()]


def locked_out(now=None):
    """People who can't sign in right now because of too many wrong PINs."""
    now = now or timezone.now()
    return list(
        User.objects.filter(status=Status.ACTIVE)
        .filter(Q(pin_reset_required=True) | Q(locked_until__gt=now))
        .order_by("first_name", "last_name")
    )
