"""Who can take which shift (SPEC §5): one function decides, and the list filter agrees with it."""

import pytest
from django.utils import timezone

from scheduling.models import Shift, ShiftKind, ShiftStatus
from tests.factories import (
    ShiftFactory,
    StaffFactory,
    TrainingTypeFactory,
    UserFactory,
    at,
    trained,
)
from training import eligibility
from training.models import TrainingNeed

pytestmark = pytest.mark.django_db


@pytest.fixture
def dog_walking():
    return TrainingTypeFactory(name="Dog walking")


def test_untrained_shifts_need_orientation_or_permission():
    shift = ShiftFactory()
    newcomer = UserFactory()
    assert eligibility.why_not(newcomer, shift) == eligibility.NEEDS_ORIENTATION
    cleared = UserFactory(profile__no_training_eligible=True)
    assert eligibility.can_take(cleared, shift)


def test_staff_can_take_untrained_shifts():
    assert eligibility.can_take(StaffFactory(), ShiftFactory())


def test_shifts_needing_training_need_a_record(dog_walking):
    shift = ShiftFactory(required_training=dog_walking)
    person = UserFactory(profile__no_training_eligible=True)
    assert eligibility.why_not(person, shift) == eligibility.NEEDS_TRAINING
    trained(person, dog_walking)
    assert eligibility.can_take(person, shift)


def test_voided_training_does_not_count(dog_walking):
    person = UserFactory()
    staff = StaffFactory()
    trained(
        person,
        dog_walking,
        voided_at=timezone.now(),
        voided_by=staff,
        void_reason="Entered by mistake",
    )
    shift = ShiftFactory(required_training=dog_walking)
    assert eligibility.why_not(person, shift) == eligibility.NEEDS_TRAINING


def test_training_sessions_are_for_people_who_need_them(dog_walking):
    session = ShiftFactory(kind=ShiftKind.TRAINING, teaches=dog_walking)
    person = UserFactory()
    assert eligibility.why_not(person, session) == eligibility.SESSION_NOT_NEEDED
    assert eligibility.can_take(person, session, staff_adding=True)
    TrainingNeed.objects.create(volunteer=person, training_type=dog_walking)
    assert eligibility.can_take(person, session)


def test_cancelled_and_started_shifts_are_closed():
    person = UserFactory(profile__no_training_eligible=True)
    cancelled = ShiftFactory(status=ShiftStatus.CANCELLED)
    started = ShiftFactory(starts_at=at(0, 0), ends_at=at(1, 23))
    assert eligibility.why_not(person, cancelled) == eligibility.CANCELLED
    assert eligibility.why_not(person, started, now=at(0, 1)) == eligibility.STARTED


def test_turned_off_people_cannot_take_shifts():
    person = UserFactory(status="inactive", profile__no_training_eligible=True)
    assert eligibility.why_not(person, ShiftFactory()) == eligibility.TURNED_OFF


def test_list_filter_agrees_with_the_rule(dog_walking):
    cats = TrainingTypeFactory(name="Cat enrichment")
    person = UserFactory(profile__no_training_eligible=True)
    trained(person, dog_walking)
    TrainingNeed.objects.create(volunteer=person, training_type=cats)
    shifts = [
        ShiftFactory(starts_at=at(1, 7)),
        ShiftFactory(starts_at=at(1, 9), required_training=dog_walking),
        ShiftFactory(starts_at=at(1, 11), required_training=cats),
        ShiftFactory(starts_at=at(1, 13), kind=ShiftKind.TRAINING, teaches=cats),
        ShiftFactory(starts_at=at(1, 15), kind=ShiftKind.TRAINING, teaches=dog_walking),
        ShiftFactory(starts_at=at(1, 17), status=ShiftStatus.CANCELLED),
    ]
    by_filter = set(Shift.objects.filter(eligibility.eligible_filter(person)))
    by_rule = {s for s in shifts if eligibility.can_take(person, s)}
    assert by_filter == by_rule
    assert len(by_rule) == 3
