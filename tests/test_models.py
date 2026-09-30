"""The database itself refuses bad data (SPEC §5): these are the backstops behind the services."""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from accounts.models import Skill, User
from core.models import AuditEvent, ShelterSettings
from scheduling.models import ShiftKind, SignupStatus, WaitlistEntry
from tests.factories import ShiftFactory, SignupFactory, TrainingTypeFactory, UserFactory, at

pytestmark = pytest.mark.django_db


@contextmanager
def _refused():
    """Expect the database to refuse, without breaking the test's transaction."""
    with pytest.raises(IntegrityError), transaction.atomic():
        yield


def test_sign_in_names_are_unique_ignoring_capitals():
    UserFactory(first_name="Mary", last_name="Smith")
    with _refused():
        User.objects.create_user("mary SMITH")


def test_skills_start_with_the_shelters_list():
    names = set(Skill.objects.values_list("name", flat=True))
    assert {"Dog walking", "Cat enrichment", "Special events"} <= names


def test_nobody_can_hold_overlapping_shifts():
    person = UserFactory()
    SignupFactory(volunteer=person, shift=ShiftFactory(starts_at=at(1, 9)))
    overlapping = ShiftFactory(starts_at=at(1, 10))
    with _refused():
        SignupFactory(volunteer=person, shift=overlapping)


def test_back_to_back_shifts_are_fine():
    person = UserFactory()
    SignupFactory(volunteer=person, shift=ShiftFactory(starts_at=at(1, 9)))
    SignupFactory(volunteer=person, shift=ShiftFactory(starts_at=at(1, 11)))


def test_cancelled_signups_do_not_block_other_shifts():
    person = UserFactory()
    SignupFactory(
        volunteer=person, shift=ShiftFactory(starts_at=at(1, 9)), status=SignupStatus.CANCELLED
    )
    SignupFactory(volunteer=person, shift=ShiftFactory(starts_at=at(1, 10)))


def test_a_double_tap_cannot_sign_up_twice():
    signup = SignupFactory()
    with _refused():
        SignupFactory(volunteer=signup.volunteer, shift=signup.shift)


def test_only_one_training_type_can_be_orientation():
    TrainingTypeFactory(is_orientation=True)
    with _refused():
        TrainingTypeFactory(is_orientation=True)


@pytest.mark.parametrize(
    "fields",
    [
        {"ends_at": at(1, 8)},
        {"capacity": 0},
        {"kind": ShiftKind.TRAINING},
    ],
    ids=["ends-before-start", "no-capacity", "training-without-subject"],
)
def test_impossible_shifts_are_refused(fields):
    with _refused():
        ShiftFactory(**fields)


def test_training_sessions_say_what_they_teach():
    topic = TrainingTypeFactory()
    ShiftFactory(kind=ShiftKind.TRAINING, teaches=topic)


def test_waitlist_holds_each_person_once_per_shift():
    shift, person = ShiftFactory(), UserFactory()
    WaitlistEntry.objects.create(shift=shift, volunteer=person)
    with _refused():
        WaitlistEntry.objects.create(shift=shift, volunteer=person)


def test_local_date_uses_shelter_time_not_utc():
    late_evening = timezone.make_aware(datetime(2026, 11, 1, 23, 30))
    shift = ShiftFactory(starts_at=late_evening, ends_at=late_evening + timedelta(minutes=29))
    assert str(shift.local_date) == "2026-11-01"


def test_change_log_entries_are_permanent():
    event = AuditEvent.objects.create(action="account.created")
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()


def test_shelter_settings_is_a_single_row(settings):
    settings.SHELTER_PHONE = "(740) 555-0100"
    first = ShelterSettings.load()
    assert first.shelter_phone == "(740) 555-0100"
    assert ShelterSettings.load().pk == first.pk == 1
    with _refused():
        ShelterSettings.objects.create(pk=2, shelter_name="Second")


def test_signup_period_is_a_real_range():
    signup = SignupFactory()
    assert isinstance(signup.period, DateTimeTZRange)
