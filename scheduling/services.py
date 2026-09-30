"""The booking rules (SPEC §6, Phase 3). Every screen goes through these.

Each change locks the shift's row first, so two people can't take the last spot
at once. Services check and explain problems; database constraints are the backstop.
"""

import enum
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from core import audit
from core.models import ShelterSettings
from scheduling.models import (
    WAITLIST_MAX,
    RequestStatus,
    Shift,
    ShiftStatus,
    Signup,
    SignupRequest,
    SignupStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from training import eligibility


class Problem(enum.Enum):
    FULL = "full"
    NOT_ELIGIBLE = "not_eligible"
    OVERLAP = "overlap"
    CANCELLED = "cancelled"
    STARTED = "started"
    WAITLIST_FULL = "waitlist_full"
    HAS_SPACE = "has_space"
    NOT_WAITING = "not_waiting"
    CAPACITY_BELOW_SIGNUPS = "capacity_below_signups"
    TIME_CLASH = "time_clash"
    MISSING_TRAINING = "missing_training"
    NEEDS_APPROVAL = "needs_approval"
    NO_APPROVAL_NEEDED = "no_approval_needed"
    ALREADY_ANSWERED = "already_answered"


@dataclass
class Result:
    ok: bool
    problem: Problem | None = None
    reason: str | None = None  # eligibility reason for NOT_ELIGIBLE
    signup: Signup | None = None
    entry: WaitlistEntry | None = None
    signup_request: SignupRequest | None = None
    other_shift: Shift | None = None  # the shift it overlaps
    already: bool = False  # the request was already done (e.g. a double tap)
    late: bool = False
    people: list | None = None  # who blocks a staff change

    @classmethod
    def fail(cls, problem, **kwargs):
        """A refused request."""
        return cls(ok=False, problem=problem, **kwargs)


def _locked(shift) -> Shift:
    return Shift.objects.select_for_update().get(pk=shift.pk)


def _period(shift) -> DateTimeTZRange:
    return DateTimeTZRange(shift.starts_at, shift.ends_at)


def confirmed_count(shift) -> int:
    """How many people are signed up."""
    return shift.signups.filter(status=SignupStatus.CONFIRMED).count()


def _clash(volunteer, starts_at, ends_at, *, excluding_shift) -> Signup | None:
    return (
        Signup.objects.filter(
            volunteer=volunteer,
            status=SignupStatus.CONFIRMED,
            period__overlap=DateTimeTZRange(starts_at, ends_at),
        )
        .exclude(shift=excluding_shift)
        .select_related("shift")
        .first()
    )


def _notify_after_commit(func, *args, **kwargs):
    transaction.on_commit(lambda: func(*args, **kwargs))


def _refusal(reason) -> Result | None:
    """An eligibility reason as a refused Result (None if they're eligible)."""
    if reason == eligibility.CANCELLED:
        return Result.fail(Problem.CANCELLED)
    if reason == eligibility.STARTED:
        return Result.fail(Problem.STARTED)
    if reason:
        return Result.fail(Problem.NOT_ELIGIBLE, reason=reason)
    return None


def needs_approval(volunteer, shift) -> bool:
    """Staff approve this sign-up: the shift needs it, or the person does (SPEC §6, Phase 9).

    Staff never need approval; they're the ones who give it.
    """
    if volunteer.is_staff_member:
        return False
    if shift.needs_approval:
        return True
    profile = getattr(volunteer, "profile", None)
    return bool(profile and profile.needs_approval)


@transaction.atomic
def sign_up(volunteer, shift, *, by=None, now=None) -> Result:
    """Put someone on a shift, themselves or (with `by`) added by staff."""
    now = now or timezone.now()
    by = by or volunteer
    staff_adding = by.pk != volunteer.pk
    shift = _locked(shift)

    existing = Signup.objects.filter(
        shift=shift, volunteer=volunteer, status=SignupStatus.CONFIRMED
    ).first()
    if existing:
        return Result(ok=True, signup=existing, already=True)

    refused = _refusal(eligibility.why_not(volunteer, shift, staff_adding=staff_adding, now=now))
    if refused:
        return refused
    if not staff_adding and needs_approval(volunteer, shift):
        return Result.fail(Problem.NEEDS_APPROVAL)
    if confirmed_count(shift) >= shift.capacity:
        return Result.fail(Problem.FULL)
    clash = _clash(volunteer, shift.starts_at, shift.ends_at, excluding_shift=shift)
    if clash:
        return Result.fail(Problem.OVERLAP, other_shift=clash.shift)

    try:
        with transaction.atomic():
            signup = Signup.objects.create(
                shift=shift, volunteer=volunteer, period=_period(shift), created_by=by
            )
    except IntegrityError:
        # Another request for the same person won the race; the database refused this one.
        return Result.fail(Problem.OVERLAP)

    WaitlistEntry.objects.filter(
        shift=shift, volunteer=volunteer, status=WaitlistStatus.WAITING
    ).update(status=WaitlistStatus.PROMOTED, resolved_at=now, resolved_by=by)
    # Being on the shift answers any request to join it, however they got there.
    SignupRequest.objects.filter(
        shift=shift, volunteer=volunteer, status=RequestStatus.WAITING
    ).update(status=RequestStatus.APPROVED, resolved_at=now, resolved_by=by)
    audit.record(
        "shift.added_by_staff" if staff_adding else "shift.signed_up",
        actor=by,
        target_user=volunteer,
        target_repr=str(shift),
        shift=shift.pk,
        at=now,
    )
    return Result(ok=True, signup=signup)


def is_late(shift, now=None) -> bool:
    """Inside the self-service window, a volunteer's cancellation is "late"."""
    now = now or timezone.now()
    window = timedelta(hours=ShelterSettings.load().self_cancel_hours)
    return shift.starts_at - now < window


def is_urgent(shift, now=None) -> bool:
    """A cancellation this close to the shift is urgent: staff are emailed straight away.

    The threshold is a setting (24 or 48 hours) so the pilot can try both (SPEC §6).
    """
    now = now or timezone.now()
    window = timedelta(hours=ShelterSettings.load().urgent_threshold_hours)
    return shift.starts_at - now < window


@transaction.atomic
def cancel_signup(signup, *, by, reason="", now=None) -> Result:
    """A volunteer cancels (late if inside the window), or staff take someone off a shift."""
    now = now or timezone.now()
    shift = _locked(signup.shift)
    signup = Signup.objects.select_for_update().get(pk=signup.pk)
    if signup.status != SignupStatus.CONFIRMED:
        return Result(ok=True, signup=signup, already=True)
    by_volunteer = by.pk == signup.volunteer_id
    if by_volunteer and shift.starts_at <= now:
        return Result.fail(Problem.STARTED)

    late = by_volunteer and is_late(shift, now)
    urgent = by_volunteer and is_urgent(shift, now)
    signup.status = SignupStatus.CANCELLED
    signup.cancelled_at = now
    signup.cancelled_by = by
    signup.cancel_reason = reason[:200]
    signup.is_late_cancel = late
    signup.was_urgent = urgent
    signup.save()
    audit.record(
        "shift.cancelled" if by_volunteer else "shift.removed_by_staff",
        actor=by,
        target_user=signup.volunteer,
        target_repr=str(shift),
        shift=shift.pk,
        late=late,
        urgent=urgent,
        at=now,
    )
    if urgent:
        from scheduling import notices

        _notify_after_commit(notices.late_cancellation, signup)
    return Result(ok=True, signup=signup, late=late)


@transaction.atomic
def join_waitlist(volunteer, shift, *, now=None) -> Result:
    """Wait for a spot on a full shift (at most 10 people wait)."""
    now = now or timezone.now()
    shift = _locked(shift)
    if Signup.objects.filter(
        shift=shift, volunteer=volunteer, status=SignupStatus.CONFIRMED
    ).exists():
        return Result(ok=True, already=True)
    waiting = WaitlistEntry.objects.filter(shift=shift, status=WaitlistStatus.WAITING)
    mine = waiting.filter(volunteer=volunteer).first()
    if mine:
        return Result(ok=True, entry=mine, already=True)
    refused = _refusal(eligibility.why_not(volunteer, shift, now=now))
    if refused:
        return refused
    if confirmed_count(shift) < shift.capacity:
        return Result.fail(Problem.HAS_SPACE)
    if waiting.count() >= WAITLIST_MAX:
        return Result.fail(Problem.WAITLIST_FULL)
    clash = _clash(volunteer, shift.starts_at, shift.ends_at, excluding_shift=shift)
    if clash:
        return Result.fail(Problem.OVERLAP, other_shift=clash.shift)
    entry = WaitlistEntry.objects.create(shift=shift, volunteer=volunteer, created_at=now)
    audit.record(
        "waitlist.joined", actor=volunteer, target_user=volunteer, target_repr=str(shift), at=now
    )
    return Result(ok=True, entry=entry)


@transaction.atomic
def leave_waitlist(entry, *, by, now=None) -> Result:
    """The volunteer leaves the waitlist, or staff take them off it."""
    now = now or timezone.now()
    _locked(entry.shift)
    entry = WaitlistEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status != WaitlistStatus.WAITING:
        return Result(ok=True, entry=entry, already=True)
    by_volunteer = by.pk == entry.volunteer_id
    entry.status = WaitlistStatus.LEFT if by_volunteer else WaitlistStatus.REMOVED
    entry.resolved_at = now
    entry.resolved_by = by
    entry.save()
    audit.record(
        "waitlist.left" if by_volunteer else "waitlist.removed",
        actor=by,
        target_user=entry.volunteer,
        target_repr=str(entry.shift),
        at=now,
    )
    return Result(ok=True, entry=entry)


@transaction.atomic
def promote_from_waitlist(entry, *, by, now=None) -> Result:
    """Staff move someone from the waitlist onto the shift; they get a "good news" email."""
    now = now or timezone.now()
    entry = WaitlistEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status != WaitlistStatus.WAITING:
        return Result.fail(Problem.NOT_WAITING)
    result = sign_up(entry.volunteer, entry.shift, by=by, now=now)
    if result.ok and not result.already:
        from scheduling import notices

        _notify_after_commit(notices.promoted_from_waitlist, result.signup)
    return result


@transaction.atomic
def update_shift(shift, *, by, now=None, **changes) -> Result:
    """Staff change a shift. Refused if it would squeeze out or double-book signed-up people."""
    now = now or timezone.now()
    shift = _locked(shift)
    signups = list(shift.signups.filter(status=SignupStatus.CONFIRMED).select_related("volunteer"))
    capacity = changes.get("capacity", shift.capacity)
    if capacity < len(signups):
        return Result.fail(Problem.CAPACITY_BELOW_SIGNUPS, people=[s.volunteer for s in signups])
    starts_at = changes.get("starts_at", shift.starts_at)
    ends_at = changes.get("ends_at", shift.ends_at)
    clashes = [
        s.volunteer
        for s in signups
        if _clash(s.volunteer, starts_at, ends_at, excluding_shift=shift)
    ]
    if clashes:
        return Result.fail(Problem.TIME_CLASH, people=clashes)
    training = changes.get("required_training", shift.required_training)
    if training and training != shift.required_training:
        untrained = [
            s.volunteer
            for s in signups
            if training.pk not in eligibility.trained_type_ids(s.volunteer)
        ]
        if untrained:
            return Result.fail(Problem.MISSING_TRAINING, people=untrained)

    changed = []
    for field, value in changes.items():
        if getattr(shift, field) != value:
            setattr(shift, field, value)
            changed.append(field)
    if not changed:
        return Result(ok=True, already=True)
    shift.edited_by_hand = True
    shift.save()
    if {"starts_at", "ends_at"} & set(changed):
        Signup.objects.filter(shift=shift, status=SignupStatus.CONFIRMED).update(
            period=_period(shift)
        )
    audit.record("shift.edited", actor=by, target_repr=str(shift), fields=changed, at=now)
    return Result(ok=True)


@transaction.atomic
def cancel_shift(shift, *, by, reason, now=None) -> Result:
    """Cancel a whole shift: everyone on it is taken off and emailed."""
    now = now or timezone.now()
    shift = _locked(shift)
    if shift.status == ShiftStatus.CANCELLED:
        return Result(ok=True, already=True)
    shift.status = ShiftStatus.CANCELLED
    shift.cancel_reason = reason[:200]
    shift.save(update_fields=["status", "cancel_reason"])
    signups = list(shift.signups.filter(status=SignupStatus.CONFIRMED))
    Signup.objects.filter(pk__in=[s.pk for s in signups]).update(
        status=SignupStatus.CANCELLED,
        cancelled_at=now,
        cancelled_by=by,
        cancel_reason="The shift was cancelled.",
    )
    WaitlistEntry.objects.filter(shift=shift, status=WaitlistStatus.WAITING).update(
        status=WaitlistStatus.REMOVED, resolved_at=now, resolved_by=by
    )
    asked = list(shift.requests.filter(status=RequestStatus.WAITING).select_related("volunteer"))
    SignupRequest.objects.filter(pk__in=[r.pk for r in asked]).update(
        status=RequestStatus.CLOSED, resolved_at=now, resolved_by=by
    )
    audit.record(
        "shift.cancelled_by_staff",
        actor=by,
        target_repr=str(shift),
        reason=reason,
        people=len(signups),
        at=now,
    )
    from scheduling import notices

    for signup in signups:
        _notify_after_commit(notices.shift_cancelled, signup, reason)
    for signup_request in asked:
        _notify_after_commit(notices.asked_shift_cancelled, signup_request, reason)
    return Result(ok=True)


def expire_past_waitlists(now=None) -> int:
    """Waitlist entries for shifts that have started are closed."""
    now = now or timezone.now()
    return WaitlistEntry.objects.filter(
        status=WaitlistStatus.WAITING, shift__starts_at__lte=now
    ).update(status=WaitlistStatus.EXPIRED, resolved_at=now)


def close_past_requests(now=None) -> int:
    """Requests nobody answered before the shift started are closed."""
    now = now or timezone.now()
    return SignupRequest.objects.filter(
        status=RequestStatus.WAITING, shift__starts_at__lte=now
    ).update(status=RequestStatus.CLOSED, resolved_at=now)


@transaction.atomic
def ask_to_join(volunteer, shift, *, now=None) -> Result:
    """Ask staff for a place on a shift that needs approval. It holds no spot until approved."""
    now = now or timezone.now()
    shift = _locked(shift)
    if Signup.objects.filter(
        shift=shift, volunteer=volunteer, status=SignupStatus.CONFIRMED
    ).exists():
        return Result(ok=True, already=True)
    mine = SignupRequest.objects.filter(
        shift=shift, volunteer=volunteer, status=RequestStatus.WAITING
    ).first()
    if mine:
        return Result(ok=True, signup_request=mine, already=True)
    refused = _refusal(eligibility.why_not(volunteer, shift, now=now))
    if refused:
        return refused
    if not needs_approval(volunteer, shift):
        return Result.fail(Problem.NO_APPROVAL_NEEDED)
    if confirmed_count(shift) >= shift.capacity:
        return Result.fail(Problem.FULL)
    clash = _clash(volunteer, shift.starts_at, shift.ends_at, excluding_shift=shift)
    if clash:
        return Result.fail(Problem.OVERLAP, other_shift=clash.shift)
    signup_request = SignupRequest.objects.create(shift=shift, volunteer=volunteer, created_at=now)
    audit.record(
        "request.asked", actor=volunteer, target_user=volunteer, target_repr=str(shift), at=now
    )
    return Result(ok=True, signup_request=signup_request)


def _locked_request(signup_request) -> SignupRequest:
    # The shift first, then the request: the same order as every other booking change.
    _locked(signup_request.shift)
    return SignupRequest.objects.select_for_update().get(pk=signup_request.pk)


@transaction.atomic
def approve_request(signup_request, *, by, now=None) -> Result:
    """Staff say yes: the person is booked, with the same checks as staff adding them."""
    now = now or timezone.now()
    signup_request = _locked_request(signup_request)
    if signup_request.status != RequestStatus.WAITING:
        return Result.fail(Problem.ALREADY_ANSWERED)
    result = sign_up(signup_request.volunteer, signup_request.shift, by=by, now=now)
    if not result.ok:
        return result
    SignupRequest.objects.filter(pk=signup_request.pk, status=RequestStatus.WAITING).update(
        status=RequestStatus.APPROVED, resolved_at=now, resolved_by=by
    )
    audit.record(
        "request.approved",
        actor=by,
        target_user=signup_request.volunteer,
        target_repr=str(signup_request.shift),
        at=now,
    )
    if not result.already:
        from scheduling import notices

        _notify_after_commit(notices.request_approved, result.signup)
    return result


@transaction.atomic
def decline_request(signup_request, *, by, note="", now=None) -> Result:
    """Staff say no. The volunteer is emailed, with the note if there is one."""
    now = now or timezone.now()
    signup_request = _locked_request(signup_request)
    if signup_request.status != RequestStatus.WAITING:
        return Result.fail(Problem.ALREADY_ANSWERED)
    signup_request.status = RequestStatus.DECLINED
    signup_request.resolved_at = now
    signup_request.resolved_by = by
    signup_request.note = note[:300]
    signup_request.save()
    audit.record(
        "request.declined",
        actor=by,
        target_user=signup_request.volunteer,
        target_repr=str(signup_request.shift),
        at=now,
    )
    from scheduling import notices

    _notify_after_commit(notices.request_declined, signup_request)
    return Result(ok=True, signup_request=signup_request)


@transaction.atomic
def withdraw_request(signup_request, *, by, now=None) -> Result:
    """The volunteer takes back their request."""
    now = now or timezone.now()
    signup_request = _locked_request(signup_request)
    if signup_request.status != RequestStatus.WAITING:
        return Result(ok=True, signup_request=signup_request, already=True)
    signup_request.status = RequestStatus.WITHDRAWN
    signup_request.resolved_at = now
    signup_request.resolved_by = by
    signup_request.save()
    audit.record(
        "request.withdrawn",
        actor=by,
        target_user=signup_request.volunteer,
        target_repr=str(signup_request.shift),
        at=now,
    )
    return Result(ok=True, signup_request=signup_request)


def waiting_requests(now=None):
    """Requests staff haven't answered yet, for shifts still to come, soonest shift first."""
    now = now or timezone.now()
    return (
        SignupRequest.objects.filter(
            status=RequestStatus.WAITING,
            shift__status=ShiftStatus.SCHEDULED,
            shift__starts_at__gt=now,
        )
        .select_related("shift", "volunteer", "volunteer__profile")
        .order_by("shift__starts_at", "shift_id", "created_at")
    )
