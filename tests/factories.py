"""Test data builders. Everyone's PIN is TEST_PIN unless a test says otherwise."""

from datetime import date, datetime, time, timedelta

import factory
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from accounts.models import Role, User, VolunteerProfile
from scheduling.models import Shift, ShiftKind, ShiftPattern, Signup, TemplateWeek
from training.models import TrainingRecord, TrainingType

TEST_PIN = "482916"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    first_name = factory.Sequence(lambda n: f"Pat{n}")
    last_name = "Tester"
    login_name = factory.LazyAttribute(lambda o: f"{o.first_name} {o.last_name}")
    email = factory.LazyAttribute(lambda o: f"{o.first_name.lower()}@example.com")
    phone = "7405550100"
    role = Role.VOLUNTEER
    profile = factory.RelatedFactory(
        "tests.factories.VolunteerProfileFactory", factory_related_name="user"
    )

    @factory.post_generation
    def pin(obj, create, extracted, **kwargs):
        """Set the PIN (TEST_PIN by default)."""
        obj.set_password(extracted or TEST_PIN)
        if create:
            obj.save(update_fields=["password"])


class StaffFactory(UserFactory):
    role = Role.STAFF
    job_title = "Volunteer Lead"


class AdminFactory(UserFactory):
    role = Role.ADMIN
    is_staff = True
    is_superuser = True


class VolunteerProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VolunteerProfile

    user = factory.SubFactory(UserFactory, profile=None)


class TrainingTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrainingType

    name = factory.Sequence(lambda n: f"Training {n}")


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """A shelter-time moment `day_offset` days from today."""
    day = timezone.localdate() + timedelta(days=day_offset)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class ShiftFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Shift

    title = "Dog walking"
    kind = ShiftKind.REGULAR
    starts_at = factory.LazyFunction(lambda: at(1, 9))
    ends_at = factory.LazyAttribute(lambda o: o.starts_at + timedelta(hours=2))
    capacity = 3


class SignupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Signup

    shift = factory.SubFactory(ShiftFactory)
    volunteer = factory.SubFactory(UserFactory)
    period = factory.LazyAttribute(lambda o: DateTimeTZRange(o.shift.starts_at, o.shift.ends_at))


class TemplateWeekFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TemplateWeek

    name = factory.Sequence(lambda n: f"Week {n}")


class PatternFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShiftPattern

    template_week = factory.SubFactory(TemplateWeekFactory)
    title = "Morning dog walking"
    weekday = 3  # Thursday
    start_time = time(9)
    end_time = time(11)
    capacity = 2
    active_from = date(2026, 10, 1)
    anchor_date = factory.LazyAttribute(lambda o: o.active_from)


def trained(person, training_type, **kwargs):
    """Give someone a completed training record."""
    return TrainingRecord.objects.create(
        volunteer=person,
        training_type=training_type,
        completed_on=kwargs.pop("completed_on", timezone.localdate()),
        signed_off_by=kwargs.pop("signed_off_by", person),
        **kwargs,
    )
