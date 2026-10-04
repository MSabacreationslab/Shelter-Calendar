"""Fill the test site with fake people, training and a month of shifts (DEMO_MODE only)."""

import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts import services
from accounts.models import Role, Skill, User
from accounts.pins import pin_problem
from scheduling import generation, planning
from scheduling import services as booking
from scheduling.models import (
    Shift,
    ShiftKind,
    ShiftStatus,
    Signup,
    SignupStatus,
    TemplateWeek,
    WaitlistStatus,
)
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
# A starting list for the test site; staff can add, rename or turn off trainings (Q20).
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
# What each demo volunteer has done, besides orientation (which they've all had). Spread so
# every kind of shift has a few people who can take it.
DEMO_TRAINING = {
    "Alex": ["Dog walking"],
    "Blair": ["Dog walking", "Cat enrichment"],
    "Charlie": ["Dog walking", "Dog kennel cleaning"],
    "Dana": ["Cat enrichment", "Cat cage cleaning"],
    "Emery": ["Dog walking", "Dog kennel cleaning"],
    "Frankie": ["Cat enrichment", "Cat cage cleaning"],
    "Gale": ["Dog walking", "Cat enrichment"],
    "Harper": ["Cat enrichment", "Dog kennel cleaning"],
    "Indigo": ["Dog walking", "Cat cage cleaning"],
    "Jordan": ["Cat enrichment"],
}
MINOR = "Alex"
NEEDS_APPROVAL = "Jordan"
CANCEL_REASON = "Not feeling well today, sorry!"


class Command(BaseCommand):
    help = "Create demo staff and volunteers and four weeks of staffed shifts. Safe to run again."

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
        self._approval_examples(volunteers, lead)
        self._cancellation_example(volunteers)
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
        """Everyone has done orientation and a couple of trainings; one is a minor and one
        needs approval for every shift."""
        today = timezone.localdate()
        for person in volunteers:
            for name in ["Orientation", *DEMO_TRAINING[person.first_name]]:
                TrainingRecord.objects.get_or_create(
                    volunteer=person,
                    training_type=types[name],
                    defaults={"completed_on": today, "trainer": lead, "signed_off_by": lead},
                )
            profile = person.profile
            profile.no_training_eligible = True
            profile.is_minor = person.first_name == MINOR
            profile.needs_approval = person.first_name == NEEDS_APPROVAL
            profile.save(update_fields=["no_training_eligible", "is_minor", "needs_approval"])

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
        """Fill the next four weeks so the schedule looks lived-in: most shifts one person
        short, every fourth one full with someone waiting, and some left wide open."""
        now = timezone.now()
        regulars = [p for p in volunteers if p.first_name != NEEDS_APPROVAL]
        shifts = Shift.objects.filter(
            kind=ShiftKind.REGULAR,
            status=ShiftStatus.SCHEDULED,
            needs_approval=False,
            starts_at__gt=now,
            starts_at__lte=now + timedelta(days=FILL_DAYS + 1),
        ).order_by("starts_at", "pk")
        count = 0
        for k, shift in enumerate(shifts):
            if k % 5 == 4:
                continue  # nobody yet, so "open spots" lists have something to show
            full = k % 4 == 0
            target = shift.capacity if full else max(shift.capacity - 1, 1)
            turn = k % len(regulars)
            queue = regulars[turn:] + regulars[:turn]
            for person in queue:
                if booking.confirmed_count(shift) >= target:
                    break
                result = booking.sign_up(person, shift)
                count += result.ok and not result.already
            waiting = shift.waitlist.filter(status=WaitlistStatus.WAITING).exists()
            if full and not waiting and booking.confirmed_count(shift) >= shift.capacity:
                for person in queue:
                    if booking.join_waitlist(person, shift).entry:
                        break
        return count

    def _approval_examples(self, volunteers, lead):
        """A large event that needs approval with two people asking, one of them the
        volunteer who needs approval for everything; they've also asked for a normal shift."""
        by_name = {person.first_name: person for person in volunteers}
        returning = by_name[NEEDS_APPROVAL]
        today = timezone.localdate()
        saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        event = Shift.objects.filter(title="Adoption event", local_date=saturday).first()
        if event is None:
            event = planning.create_shift(
                {
                    "title": "Adoption event",
                    "kind": ShiftKind.REGULAR,
                    "starts_at": timezone.make_aware(datetime.combine(saturday, time(11))),
                    "ends_at": timezone.make_aware(datetime.combine(saturday, time(15))),
                    "capacity": 10,
                    "needs_approval": True,
                    "notes": "Meet at the front desk.",
                },
                by=lead,
            )
        booking.ask_to_join(by_name["Blair"], event)
        booking.ask_to_join(returning, event)
        ordinary = Shift.objects.filter(
            kind=ShiftKind.REGULAR,
            status=ShiftStatus.SCHEDULED,
            needs_approval=False,
            starts_at__gt=timezone.now() + timedelta(days=2),
        ).order_by("starts_at")
        for shift in ordinary[:20]:
            if booking.ask_to_join(returning, shift).ok:
                break

    def _cancellation_example(self, volunteers):
        """One last-minute cancellation for the dashboard. Written directly rather than
        through the booking service, so seeding never emails the notify list."""
        now = timezone.now()
        if Signup.objects.filter(cancel_reason=CANCEL_REASON, shift__starts_at__gt=now).exists():
            return
        signup = (
            Signup.objects.filter(
                status=SignupStatus.CONFIRMED,
                volunteer__in=volunteers,
                shift__starts_at__gt=now + timedelta(hours=2),
                shift__starts_at__lte=now + timedelta(hours=48),
            )
            .order_by("shift__starts_at")
            .first()
        )
        if signup is None:
            return
        signup.status = SignupStatus.CANCELLED
        signup.cancelled_at = now
        signup.cancelled_by = signup.volunteer
        signup.cancel_reason = CANCEL_REASON
        signup.is_late_cancel = True
        signup.was_urgent = True
        signup.save()
