"""Fill the test site with fake people, training and a month of shifts (DEMO_MODE only)."""

import os
from datetime import time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts import services
from accounts.models import Role, Skill, User
from accounts.pins import pin_problem
from scheduling import generation, planning
from scheduling import services as booking
from scheduling.models import Shift, ShiftKind, TemplateWeek
from training import eligibility
from training.models import TrainingRecord, TrainingType

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
# (title, weekdays, start, end, people, training, kind, every n weeks)
REGULAR_WEEK = [
    ("Morning dog walking", [0, 2, 4], time(9), time(11), 3, "Dog walking", ShiftKind.REGULAR, 1),
    ("Cat enrichment", [1, 3], time(10), time(12), 2, "Cat enrichment", ShiftKind.REGULAR, 1),
    ("Dog kennel cleaning", [5], time(8), time(10), 2, "Dog kennel cleaning", ShiftKind.REGULAR, 1),
    ("Cat cage cleaning", [6], time(8), time(10), 2, "Cat cage cleaning", ShiftKind.REGULAR, 1),
    ("Special events prep", [2], time(13), time(15), 4, None, ShiftKind.REGULAR, 1),
    ("Orientation", [5], time(10, 30), time(12), 6, "Orientation", ShiftKind.TRAINING, 2),
]
FILL_DAYS = 27


class Command(BaseCommand):
    help = "Create demo staff, volunteers, training and a month of shifts. Safe to run again."

    @transaction.atomic
    def handle(self, *args, **options):
        """Refuses to run unless DEMO_MODE is on and DEMO_PIN is a valid PIN."""
        if not settings.DEMO_MODE:
            raise CommandError("seed_demo only runs when DEMO_MODE=1 (never on the pilot).")
        pin = os.environ.get("DEMO_PIN", "")
        problem = pin_problem(pin)
        if problem:
            raise CommandError(f"Set DEMO_PIN to a valid 6-digit PIN first. {problem}")

        types = {}
        for name, is_orientation in TRAINING_TYPES:
            types[name], _ = TrainingType.objects.get_or_create(
                name=name, defaults={"is_orientation": is_orientation}
            )

        created = self._people(pin)
        lead = User.objects.get(login_name__iexact="Robin Demo")
        volunteers = [
            User.objects.get(login_name__iexact=f"{first} {last}") for first, last in VOLUNTEERS
        ]
        self._training(volunteers, types, lead)
        shifts = self._schedule(types, lead)
        signups = self._signups(volunteers)
        self.stdout.write(
            f"Created {created} demo people and {shifts} shifts, with {signups} sign-ups. "
            "Everyone's PIN is DEMO_PIN."
        )

    def _people(self, pin) -> int:
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
                phone=f"740555{i:04d}",
            )
            user.set_password(pin)
            user.save(update_fields=["password"])
            profile = user.profile
            profile.no_training_eligible = role == Role.STAFF or i % 2 == 0
            profile.save(update_fields=["no_training_eligible"])
            if skills:
                profile.skills.add(skills[i % len(skills)])
            created += 1
        return created

    def _training(self, volunteers, types, lead):
        today = timezone.localdate()
        for i, person in enumerate(volunteers):
            done = ["Orientation", "Dog walking"] if i % 2 == 0 else ["Cat enrichment"]
            for name in done:
                TrainingRecord.objects.get_or_create(
                    volunteer=person,
                    training_type=types[name],
                    defaults={"completed_on": today, "trainer": lead, "signed_off_by": lead},
                )

    def _schedule(self, types, lead) -> int:
        today = timezone.localdate()
        week, created = TemplateWeek.objects.get_or_create(name="Regular week")
        if created:
            for title, days, start, end, people, training, kind, every in REGULAR_WEEK:
                for weekday in days:
                    is_session = kind == ShiftKind.TRAINING
                    planning.add_pattern(
                        {
                            "template_week": week,
                            "title": title,
                            "weekday": weekday,
                            "start_time": start,
                            "end_time": end,
                            "capacity": people,
                            "kind": kind,
                            "required_training": None
                            if is_session or not training
                            else types[training],
                            "teaches": types[training] if is_session else None,
                            "notes": "",
                            "every_n_weeks": every,
                            "active_from": today,
                        },
                        by=lead,
                    )
        plan = generation.plan_fill(today, today + timedelta(days=FILL_DAYS))
        return generation.apply_fill(plan, by=lead) if plan.new else 0

    def _signups(self, volunteers) -> int:
        count = 0
        upcoming = list(Shift.objects.filter(starts_at__gt=timezone.now()).order_by("starts_at"))
        for person in volunteers[:6]:
            for shift in upcoming:
                if eligibility.can_take(person, shift):
                    result = booking.sign_up(person, shift)
                    if result.ok:
                        count += not result.already
                        break
        return count
