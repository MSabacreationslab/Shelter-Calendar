"""Recording training (SPEC §6, Phase 5). Records are voided with a reason, never deleted."""

from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from core import audit
from scheduling.models import Shift, ShiftKind
from training.models import TrainingNeed, TrainingRecord, TrainingType


def _valid_records(person, training_type):
    return TrainingRecord.objects.filter(
        volunteer=person, training_type=training_type, voided_at__isnull=True
    )


def _after_recording(person: User, training_type: TrainingType, now) -> None:
    """Close their open need for it; finishing orientation opens up no-training shifts."""
    TrainingNeed.objects.filter(
        volunteer=person, training_type=training_type, resolved_at__isnull=True
    ).update(resolved_at=now)
    if training_type.is_orientation:
        profile = person.profile
        if not profile.no_training_eligible:
            profile.no_training_eligible = True
            profile.save(update_fields=["no_training_eligible"])


def _record(person, training_type, *, completed_on, trainer, by, session=None, notes="", now):
    record = TrainingRecord.objects.create(
        volunteer=person,
        training_type=training_type,
        completed_on=completed_on,
        trainer=trainer,
        signed_off_by=by,
        session=session,
        notes=notes,
        created_at=now,
    )
    _after_recording(person, training_type, now)
    audit.record(
        "training.recorded",
        actor=by,
        target_user=person,
        target_repr=training_type.name,
        completed_on=str(completed_on),
        session=session.pk if session else None,
        at=now,
    )
    return record


@transaction.atomic
def record_session(
    session: Shift,
    people: list[User],
    *,
    completed_on: date,
    trainer: User | None,
    by: User,
    notes: str = "",
) -> list[TrainingRecord]:
    """Everyone who came to a training session gets a record, in one all-or-nothing save.

    Recording the same person for the same session twice does nothing the second time.
    """
    if session.kind != ShiftKind.TRAINING or session.teaches_id is None:
        raise ValueError("Only training sessions have attendance to record.")
    now = timezone.now()
    session = Shift.objects.select_for_update().get(pk=session.pk)
    already = set(
        TrainingRecord.objects.filter(session=session, voided_at__isnull=True).values_list(
            "volunteer_id", flat=True
        )
    )
    return [
        _record(
            person,
            session.teaches,
            completed_on=completed_on,
            trainer=trainer,
            by=by,
            session=session,
            notes=notes,
            now=now,
        )
        for person in people
        if person.pk not in already
    ]


@transaction.atomic
def record_one(
    person: User,
    training_type: TrainingType,
    *,
    completed_on: date,
    trainer: User | None,
    by: User,
    notes: str = "",
) -> TrainingRecord:
    """One record outside any session, e.g. training done before the app existed."""
    return _record(
        person,
        training_type,
        completed_on=completed_on,
        trainer=trainer,
        by=by,
        notes=notes,
        now=timezone.now(),
    )


@transaction.atomic
def void_record(record: TrainingRecord, *, reason: str, by: User) -> bool:
    """Mark a mistaken record as void. Returns True if that also took away no-training shifts.

    Voiding someone's only orientation turns off no-training shifts for them (it was
    turned on by recording it); staff can turn it back on from the person's page.
    """
    now = timezone.now()
    record = TrainingRecord.objects.select_for_update().get(pk=record.pk)
    if record.voided_at is not None:
        return False
    record.voided_at = now
    record.voided_by = by
    record.void_reason = reason[:200]
    record.save(update_fields=["voided_at", "voided_by", "void_reason"])
    audit.record(
        "training.voided",
        actor=by,
        target_user=record.volunteer,
        target_repr=record.training_type.name,
        reason=reason,
        at=now,
    )
    person = record.volunteer
    lost_access = (
        record.training_type.is_orientation
        and not person.is_staff_member
        and not _valid_records(person, record.training_type).exists()
        and person.profile.no_training_eligible
    )
    if lost_access:
        person.profile.no_training_eligible = False
        person.profile.save(update_fields=["no_training_eligible"])
    return lost_access


@transaction.atomic
def add_need(person: User, training_type: TrainingType, *, by: User) -> TrainingNeed:
    """Note a training someone still needs (lets them see and join its sessions)."""
    need, created = TrainingNeed.objects.get_or_create(
        volunteer=person,
        training_type=training_type,
        resolved_at=None,
        defaults={"created_by": by},
    )
    if created:
        audit.record(
            "training.need_added", actor=by, target_user=person, target_repr=training_type.name
        )
    return need


@transaction.atomic
def remove_need(need: TrainingNeed, *, by: User) -> None:
    """They don't need it after all. Kept, closed, for the record."""
    if need.resolved_at is None:
        need.resolved_at = timezone.now()
        need.save(update_fields=["resolved_at"])
        audit.record(
            "training.need_removed",
            actor=by,
            target_user=need.volunteer,
            target_repr=need.training_type.name,
        )


@transaction.atomic
def set_no_training_allowed(person: User, allowed: bool, *, by: User) -> None:
    """Staff decide whether someone may take shifts that need no training."""
    profile = person.profile
    if profile.no_training_eligible != allowed:
        profile.no_training_eligible = allowed
        profile.save(update_fields=["no_training_eligible"])
        audit.record("volunteer.no_training_changed", actor=by, target_user=person, allowed=allowed)


@transaction.atomic
def add_type(name: str, *, is_orientation: bool = False, by: User) -> TrainingType:
    """A new kind of training, such as "Special events"."""
    training_type = TrainingType.objects.create(name=name, is_orientation=is_orientation)
    audit.record("training_type.added", actor=by, target_repr=name)
    return training_type


@transaction.atomic
def rename_type(training_type: TrainingType, name: str, *, by: User) -> None:
    """Rename a training; everyone's records and shifts keep pointing at it."""
    old = training_type.name
    training_type.name = name
    training_type.save(update_fields=["name"])
    audit.record("training_type.renamed", actor=by, target_repr=name, old_name=old)


@transaction.atomic
def set_type_active(training_type: TrainingType, active: bool, *, by: User) -> None:
    """Take a training off the lists (records and shifts keep it) or put it back."""
    training_type.active = active
    training_type.save(update_fields=["active"])
    audit.record(
        "training_type.turned_on" if active else "training_type.turned_off",
        actor=by,
        target_repr=training_type.name,
    )
