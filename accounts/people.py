"""Adding and editing volunteers, setup links, and the skills list (SPEC §6, Phase 2)."""

from django.db import transaction

from accounts import services
from accounts.emails import send_setup_email
from accounts.models import Role, SetupLinkPurpose, Skill, User
from accounts.permissions import has_capability
from core import audit
from training.models import TrainingNeed

PERSON_FIELDS = ["first_name", "last_name", "email", "phone"]
PROFILE_FIELDS = [
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
    "staff_notes",
]


def _birthday(data):
    month, day = data.get("birthday_month"), data.get("birthday_day")
    return (int(month), int(day)) if month and day else (None, None)


def _email_after_commit(person, token, purpose):
    """Send once the database change is saved, so a slow or failed email never undoes it."""
    transaction.on_commit(lambda: send_setup_email(person, token, purpose))


@transaction.atomic
def add_volunteer(data: dict, *, added_by: User) -> User:
    """Create the volunteer, their profile, training needs and a welcome link, then email it."""
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
    profile.save()
    profile.skills.set(data.get("skills", []))
    for training_type in data.get("trainings_needed", []):
        TrainingNeed.objects.create(
            volunteer=person, training_type=training_type, created_by=added_by
        )
    token = services.create_setup_link(person, purpose=SetupLinkPurpose.INVITE, created_by=added_by)
    _email_after_commit(person, token, SetupLinkPurpose.INVITE)
    return person


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
