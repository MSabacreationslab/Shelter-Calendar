"""Fill the test site with obviously fake people and training types (DEMO_MODE only)."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts import services
from accounts.models import Role, Skill, User
from accounts.pins import pin_problem
from training.models import TrainingType

STAFF = [
    ("Sam", "Demo", "Shelter Lead"),
    ("Robin", "Demo", "Volunteer Lead"),
    ("Casey", "Demo", "Volunteer Lead's Assistant"),
]
VOLUNTEERS = [
    ("Alex", "Example"),
    ("Blair", "Example"),
    ("Charlie", "Example"),
    ("Dana", "Example"),
    ("Emery", "Example"),
    ("Frankie", "Example"),
    ("Gale", "Example"),
    ("Harper", "Example"),
    ("Indigo", "Example"),
    ("Jordan", "Example"),
]
# SPEC Q20's proposed default until the shelter confirms the list.
TRAINING_TYPES = [
    ("Orientation", True),
    ("Dog walking", False),
    ("Cat enrichment", False),
    ("Dog kennel cleaning", False),
    ("Cat cage cleaning", False),
]


class Command(BaseCommand):
    help = "Create demo staff, volunteers and training types. Safe to run more than once."

    @transaction.atomic
    def handle(self, *args, **options):
        """Refuses to run unless DEMO_MODE is on and DEMO_PIN is a valid PIN."""
        if not settings.DEMO_MODE:
            raise CommandError("seed_demo only runs when DEMO_MODE=1 (never on the pilot).")
        pin = os.environ.get("DEMO_PIN", "")
        problem = pin_problem(pin)
        if problem:
            raise CommandError(f"Set DEMO_PIN to a valid 6-digit PIN first. {problem}")

        for name, is_orientation in TRAINING_TYPES:
            TrainingType.objects.get_or_create(
                name=name, defaults={"is_orientation": is_orientation}
            )

        created = 0
        people = [(f, last, Role.STAFF, title) for f, last, title in STAFF]
        people += [(f, last, Role.VOLUNTEER, "") for f, last in VOLUNTEERS]
        skills = list(Skill.objects.filter(active=True))
        for i, (first, last, role, title) in enumerate(people):
            if User.objects.filter(login_name__iexact=f"{first} {last}").exists():
                continue
            user = services.create_person(
                first_name=first,
                last_name=last,
                email=f"{first.lower()}.{last.lower()}@example.com",
                role=role,
                job_title=title,
            )
            user.set_password(pin)
            user.save(update_fields=["password"])
            profile = user.profile
            profile.no_training_eligible = role == Role.STAFF or i % 2 == 0
            profile.save(update_fields=["no_training_eligible"])
            if skills:
                profile.skills.add(skills[i % len(skills)])
            created += 1
        self.stdout.write(f"Created {created} demo people. Everyone's PIN is DEMO_PIN.")
