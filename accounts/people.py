"""Adding and editing volunteers, setup links, and the skills list (SPEC §6, Phase 2)."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts import services
from accounts.emails import send_setup_email
from accounts.models import Role, SetupLink, SetupLinkPurpose, Skill, Status, User
from accounts.permissions import has_capability
from core import audit
from scheduling import services as booking
from scheduling.models import (
    RequestStatus,
    Signup,
    SignupRequest,
    SignupStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from training.models import TrainingNeed

PERSON_FIELDS = ["first_name", "last_name", "email", "phone"]
PROFILE_FIELDS = [
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
    "staff_notes",
]
PROFILE_FLAGS = ["is_minor", "needs_approval"]


def _birthday(data):
    month, day = data.get("birthday_month"), data.get("birthday_day")
    return (int(month), int(day)) if month and day else (None, None)


def _email_after_commit(person, token, purpose, orientation_signup=None):
    """Send once the database change is saved, so a slow or failed email never undoes it."""
    transaction.on_commit(
        lambda: send_setup_email(person, token, purpose, orientation_signup=orientation_signup)
    )


@dataclass
class Added:
    person: User
    orientation_booked: bool | None  # None when no session was chosen


@transaction.atomic
def add_volunteer(data: dict, *, added_by: User) -> Added:
    """Create the volunteer, their profile, training needs, orientation and a welcome link,
    then email it."""
    person = services.create_person(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        role=Role.VOLUNTEER,
        login_name=data["login_name"],
        created_by=added_by,
        phone=data["phone"],
    )
    profile = person.profile
    for field in PROFILE_FIELDS:
        setattr(profile, field, data.get(field, ""))
    profile.birthday_month, profile.birthday_day = _birthday(data)
    profile.no_training_eligible = data.get("no_training_eligible", False)
    for flag in PROFILE_FLAGS:
        setattr(profile, flag, bool(data.get(flag, False)))
    profile.save()
    profile.skills.set(data.get("skills", []))
    for training_type in data.get("trainings_needed", []):
        TrainingNeed.objects.create(
            volunteer=person, training_type=training_type, created_by=added_by
        )
    orientation_signup, booked = None, None
    session = data.get("orientation")
    if session is not None:
        TrainingNeed.objects.get_or_create(
            volunteer=person,
            training_type=session.teaches,
            resolved_at=None,
            defaults={"created_by": added_by},
        )
        result = booking.sign_up(person, session, by=added_by)
        booked = result.ok
        orientation_signup = result.signup if result.ok else None
    token = services.create_setup_link(person, purpose=SetupLinkPurpose.INVITE, created_by=added_by)
    _email_after_commit(person, token, SetupLinkPurpose.INVITE, orientation_signup)
    return Added(person, booked)


@transaction.atomic
def update_volunteer(person: User, data: dict, *, by: User) -> list[str]:
    """Save changed details and log which fields changed (not their values)."""
    profile = person.profile
    changed = []
    for field in PERSON_FIELDS:
        if getattr(person, field) != data[field]:
            setattr(person, field, data[field])
            changed.append(field)
    for field in PROFILE_FIELDS:
        if getattr(profile, field) != data.get(field, ""):
            setattr(profile, field, data.get(field, ""))
            changed.append(field)
    for flag in PROFILE_FLAGS:
        if getattr(profile, flag) != bool(data.get(flag, False)):
            setattr(profile, flag, bool(data.get(flag, False)))
            changed.append(flag)
    birthday = _birthday(data)
    if (profile.birthday_month, profile.birthday_day) != birthday:
        profile.birthday_month, profile.birthday_day = birthday
        changed.append("birthday")
    new_skills = {skill.pk for skill in data.get("skills", [])}
    if set(profile.skills.values_list("pk", flat=True)) != new_skills:
        profile.skills.set(new_skills)
        changed.append("skills")
    if changed:
        person.save()
        profile.save()
        audit.record("volunteer.edited", actor=by, target_user=person, fields=changed)
    return changed


def can_send_link(by: User, target: User) -> bool:
    """Staff send links to volunteers and other staff; nobody can do it for the Admin."""
    if target.is_admin or not target.is_active:
        return False
    if target.role == Role.STAFF:
        return has_capability(by, "manage_staff")
    return has_capability(by, "reset_volunteer_pin")


@transaction.atomic
def send_new_setup_link(target: User, *, by: User) -> str:
    """A welcome link if they never chose a PIN, otherwise a new-PIN link. Voids older links."""
    purpose = SetupLinkPurpose.RESET if target.has_usable_password() else SetupLinkPurpose.INVITE
    token = services.create_setup_link(target, purpose=purpose, created_by=by)
    _email_after_commit(target, token, purpose)
    return purpose


@transaction.atomic
def add_skill(name: str, *, by: User) -> Skill:
    """Put a new skill on the list."""
    skill = Skill.objects.create(name=name)
    audit.record("skill.added", actor=by, target_repr=name)
    return skill


@transaction.atomic
def rename_skill(skill: Skill, name: str, *, by: User) -> None:
    """Rename a skill; everyone who had it keeps it."""
    old = skill.name
    skill.name = name
    skill.save(update_fields=["name"])
    audit.record("skill.renamed", actor=by, target_repr=name, old_name=old)


@transaction.atomic
def set_skill_active(skill: Skill, active: bool, *, by: User) -> None:
    """Take a skill off the list (people keep it) or put it back."""
    skill.active = active
    skill.save(update_fields=["active"])
    audit.record(
        "skill.turned_on" if active else "skill.turned_off", actor=by, target_repr=skill.name
    )


@transaction.atomic
def update_own_contact(person: User, data: dict) -> list[str]:
    """A volunteer changes their phone or emergency contact. Nothing else can change here."""
    profile = person.profile
    changed = []
    if person.phone != data["phone"]:
        person.phone = data["phone"]
        person.save(update_fields=["phone"])
        changed.append("phone")
    for field in (
        "emergency_contact_name",
        "emergency_contact_phone",
        "emergency_contact_relationship",
    ):
        if getattr(profile, field) != data.get(field, ""):
            setattr(profile, field, data.get(field, ""))
            changed.append(field)
    wants = bool(data.get("wants_reminders", profile.wants_reminders))
    if profile.wants_reminders != wants:
        profile.wants_reminders = wants
        changed.append("wants_reminders")
    if set(changed) - {"phone"}:
        profile.save()
    if changed:
        audit.record("profile.updated", actor=person, target_user=person, fields=changed)
    return changed


def can_manage(by: User, target: User) -> bool:
    """Staff manage volunteers with edit_volunteers and staff with manage_staff; never the Admin."""
    if target.is_admin:
        return False
    capability = "manage_staff" if target.role == Role.STAFF else "edit_volunteers"
    return has_capability(by, capability)


@transaction.atomic
def deactivate(person: User, *, by: User, now=None) -> list:
    """Turn someone off: they're taken off future shifts and waitlists and can't sign in.

    Nothing is deleted; reactivating turns them back on (their shifts don't come back).
    """
    now = now or timezone.now()
    future = list(
        Signup.objects.filter(
            volunteer=person, status=SignupStatus.CONFIRMED, shift__starts_at__gt=now
        ).select_related("shift")
    )
    for signup in future:
        booking.cancel_signup(signup, by=by, reason="Their account was turned off", now=now)
    for entry in WaitlistEntry.objects.filter(volunteer=person, status=WaitlistStatus.WAITING):
        booking.leave_waitlist(entry, by=by, now=now)
    SignupRequest.objects.filter(volunteer=person, status=RequestStatus.WAITING).update(
        status=RequestStatus.CLOSED, resolved_at=now, resolved_by=by
    )
    SetupLink.objects.filter(user=person, used_at__isnull=True, voided_at__isnull=True).update(
        voided_at=now
    )
    person.status = Status.INACTIVE
    person.deactivated_at = now
    person.save(update_fields=["status", "deactivated_at"])
    audit.record("account.deactivated", actor=by, target_user=person, shifts=len(future), at=now)
    return [s.shift for s in future]


@transaction.atomic
def reactivate(person: User, *, by: User) -> None:
    """Turn someone back on. Their old PIN works again."""
    person.status = Status.ACTIVE
    person.deactivated_at = None
    person.save(update_fields=["status", "deactivated_at"])
    audit.record("account.reactivated", actor=by, target_user=person)


@transaction.atomic
def add_staff(data: dict, *, added_by: User) -> User:
    """Add a staff member; they get the same welcome email and PIN link as volunteers."""
    person = services.create_person(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        role=Role.STAFF,
        login_name=data["login_name"],
        created_by=added_by,
        phone=data["phone"],
        job_title=data["job_title"],
    )
    token = services.create_setup_link(person, purpose=SetupLinkPurpose.INVITE, created_by=added_by)
    _email_after_commit(person, token, SetupLinkPurpose.INVITE)
    return person


@transaction.atomic
def set_job_title(person: User, title: str, *, by: User) -> None:
    """Change a staff member's job title (a label; it doesn't change what they can do)."""
    if person.job_title != title:
        old = person.job_title
        person.job_title = title
        person.save(update_fields=["job_title"])
        audit.record("staff.job_title_changed", actor=by, target_user=person, old=old, new=title)
