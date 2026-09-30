"""The booking rules (SPEC §6, Phase 3): sign-up, cancel, waitlist and staff changes."""

import threading
from datetime import timedelta

import pytest
from django.core import mail
from django.db import connection
from django.utils import timezone

from core.models import AuditEvent, ShelterSettings
from scheduling import services as booking
from scheduling.messages import explain
from scheduling.models import (
    WAITLIST_MAX,
    ShiftStatus,
    Signup,
    SignupStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from scheduling.services import Problem
from tests.factories import ShiftFactory, StaffFactory, TrainingTypeFactory, UserFactory, at
from tests.test_plain_language import banned_words_in

pytestmark = pytest.mark.django_db


def ready(**kwargs):
    """A volunteer who can take shifts that need no training."""
    return UserFactory(profile__no_training_eligible=True, **kwargs)


@pytest.fixture
def emails(django_capture_on_commit_callbacks):
    ShelterSettings.load()
    ShelterSettings.objects.update(notify_emails="lead@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        yield mail.outbox


def test_signing_up_books_the_spot_and_logs_it():
    person, shift = ready(), ShiftFactory()
    result = booking.sign_up(person, shift)
    assert result.ok and not result.already
    assert result.signup.period.lower == shift.starts_at
    assert AuditEvent.objects.filter(action="shift.signed_up", target_user=person).exists()


def test_a_double_tap_books_once():
    person, shift = ready(), ShiftFactory()
    booking.sign_up(person, shift)
    second = booking.sign_up(person, shift)
    assert second.ok and second.already
    assert Signup.objects.filter(shift=shift).count() == 1


def test_full_shifts_refuse_more_people():
    shift = ShiftFactory(capacity=1)
    booking.sign_up(ready(), shift)
    assert booking.sign_up(ready(), shift).problem == Problem.FULL


def test_overlapping_shifts_are_refused_with_the_other_shift_named():
    person = ready()
    first = ShiftFactory(title="Cat enrichment", starts_at=at(1, 9))
    booking.sign_up(person, first)
    result = booking.sign_up(person, ShiftFactory(starts_at=at(1, 10)))
    assert result.problem == Problem.OVERLAP
    assert result.other_shift == first
    assert "Cat enrichment" in explain(result)


def test_back_to_back_shifts_are_fine():
    person = ready()
    booking.sign_up(person, ShiftFactory(starts_at=at(1, 9)))
    assert booking.sign_up(person, ShiftFactory(starts_at=at(1, 11))).ok


def test_ineligible_people_are_told_why():
    dog_walking = TrainingTypeFactory(name="Dog walking")
    shift = ShiftFactory(required_training=dog_walking)
    result = booking.sign_up(ready(), shift)
    assert result.problem == Problem.NOT_ELIGIBLE
    assert explain(result, shift=shift) == (
        "You need Dog walking training before signing up for this shift."
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_people_racing_for_the_last_spot_only_one_gets_it():
    shift = ShiftFactory(capacity=1)
    people = [ready(), ready()]
    barrier = threading.Barrier(2)
    results = []

    def attempt(person):
        try:
            barrier.wait()
            results.append(booking.sign_up(person, shift))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(p,)) for p in people]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.ok for r in results) == [False, True]
    assert Signup.objects.filter(shift=shift, status=SignupStatus.CONFIRMED).count() == 1


def test_cancelling_early_is_routine(emails):
    person = ready()
    signup = booking.sign_up(person, ShiftFactory(starts_at=at(3, 9))).signup
    result = booking.cancel_signup(signup, by=person)
    assert result.ok and not result.late
    assert emails == []


def test_cancelling_inside_the_window_is_late_and_tells_staff_right_away(emails):
    person = ready()
    shift = ShiftFactory(starts_at=timezone.now() + timedelta(hours=20))
    signup = booking.sign_up(person, shift).signup
    result = booking.cancel_signup(signup, by=person, reason="Car trouble")
    assert result.late
    signup.refresh_from_db()
    assert signup.is_late_cancel and signup.status == SignupStatus.CANCELLED
    assert [m.to for m in emails] == [["lead@example.com"]]
    assert "Car trouble" in emails[0].body


def test_the_window_edge_is_exact():
    shift = ShiftFactory(starts_at=timezone.now() + timedelta(hours=24, minutes=1))
    now = timezone.now()
    assert not booking.is_late(shift, now)
    assert booking.is_late(shift, now + timedelta(minutes=2))


def test_volunteers_cannot_cancel_after_the_start():
    person = ready()
    shift = ShiftFactory(starts_at=at(1, 9))
    signup = booking.sign_up(person, shift).signup
    result = booking.cancel_signup(signup, by=person, now=shift.starts_at + timedelta(minutes=5))
    assert result.problem == Problem.STARTED


def test_staff_removing_someone_is_not_a_late_cancel():
    person, staff = ready(), StaffFactory()
    shift = ShiftFactory(starts_at=timezone.now() + timedelta(hours=2))
    signup = booking.sign_up(person, shift).signup
    result = booking.cancel_signup(signup, by=staff)
    assert result.ok and not result.late
    assert AuditEvent.objects.filter(action="shift.removed_by_staff", actor=staff).exists()


def test_waitlist_is_for_full_shifts_only():
    shift = ShiftFactory(capacity=1)
    assert booking.join_waitlist(ready(), shift).problem == Problem.HAS_SPACE
    booking.sign_up(ready(), shift)
    assert booking.join_waitlist(ready(), shift).ok


def test_waitlist_holds_at_most_ten():
    shift = ShiftFactory(capacity=1)
    booking.sign_up(ready(), shift)
    for _ in range(WAITLIST_MAX):
        assert booking.join_waitlist(ready(), shift).ok
    assert booking.join_waitlist(ready(), shift).problem == Problem.WAITLIST_FULL


def test_joining_twice_keeps_one_place():
    shift = ShiftFactory(capacity=1)
    booking.sign_up(ready(), shift)
    person = ready()
    booking.join_waitlist(person, shift)
    assert booking.join_waitlist(person, shift).already
    assert WaitlistEntry.objects.filter(shift=shift, volunteer=person).count() == 1


def test_staff_move_someone_on_when_a_spot_opens(emails):
    staff = StaffFactory()
    shift = ShiftFactory(capacity=1)
    first = ready()
    signup = booking.sign_up(first, shift).signup
    waiting = ready()
    entry = booking.join_waitlist(waiting, shift).entry
    assert booking.promote_from_waitlist(entry, by=staff).problem == Problem.FULL
    booking.cancel_signup(signup, by=first)
    result = booking.promote_from_waitlist(entry, by=staff)
    assert result.ok
    entry.refresh_from_db()
    assert entry.status == WaitlistStatus.PROMOTED
    assert emails[-1].to == [waiting.email]
    assert "Good news" in emails[-1].subject


def test_signing_up_directly_resolves_your_waitlist_place():
    shift = ShiftFactory(capacity=1)
    first = ready()
    signup = booking.sign_up(first, shift).signup
    waiting = ready()
    booking.join_waitlist(waiting, shift)
    booking.cancel_signup(signup, by=first)
    booking.sign_up(waiting, shift)
    assert WaitlistEntry.objects.get(volunteer=waiting).status == WaitlistStatus.PROMOTED


def test_leaving_the_waitlist():
    shift = ShiftFactory(capacity=1)
    booking.sign_up(ready(), shift)
    person = ready()
    entry = booking.join_waitlist(person, shift).entry
    booking.leave_waitlist(entry, by=person)
    entry.refresh_from_db()
    assert entry.status == WaitlistStatus.LEFT


def test_shrinking_a_shift_below_its_signups_is_refused_with_names():
    staff = StaffFactory()
    shift = ShiftFactory(capacity=2)
    people = [ready(first_name="Mary"), ready(first_name="Joe")]
    for person in people:
        booking.sign_up(person, shift)
    result = booking.update_shift(shift, by=staff, capacity=1)
    assert result.problem == Problem.CAPACITY_BELOW_SIGNUPS
    assert "Mary" in explain(result) and "Joe" in explain(result)


def test_moving_a_shift_into_someones_other_shift_is_refused():
    staff, person = StaffFactory(), ready()
    morning = ShiftFactory(starts_at=at(1, 9))
    afternoon = ShiftFactory(starts_at=at(1, 13))
    booking.sign_up(person, morning)
    booking.sign_up(person, afternoon)
    result = booking.update_shift(afternoon, by=staff, starts_at=at(1, 10), ends_at=at(1, 12))
    assert result.problem == Problem.TIME_CLASH


def test_moving_a_shift_moves_its_signups_too():
    staff, person = StaffFactory(), ready()
    shift = ShiftFactory(starts_at=at(1, 9))
    booking.sign_up(person, shift)
    assert booking.update_shift(shift, by=staff, starts_at=at(1, 14), ends_at=at(1, 16)).ok
    signup = Signup.objects.get(shift=shift)
    assert signup.period.lower == at(1, 14)
    shift.refresh_from_db()
    assert shift.edited_by_hand


def test_requiring_training_nobody_on_the_shift_has_is_refused():
    staff, person = StaffFactory(), ready()
    shift = ShiftFactory()
    booking.sign_up(person, shift)
    result = booking.update_shift(shift, by=staff, required_training=TrainingTypeFactory())
    assert result.problem == Problem.MISSING_TRAINING


def test_cancelling_a_shift_takes_everyone_off_and_emails_them(emails):
    staff = StaffFactory()
    shift = ShiftFactory(capacity=1)
    person = ready()
    booking.sign_up(person, shift)
    waiting = ready()
    booking.join_waitlist(waiting, shift)
    booking.cancel_shift(shift, by=staff, reason="Snow day")
    shift.refresh_from_db()
    assert shift.status == ShiftStatus.CANCELLED
    assert not Signup.objects.filter(shift=shift, status=SignupStatus.CONFIRMED).exists()
    assert WaitlistEntry.objects.get(volunteer=waiting).status == WaitlistStatus.REMOVED
    assert [m.to for m in emails] == [[person.email]]
    assert "Snow day" in emails[0].body


def test_waitlists_close_when_the_shift_starts():
    shift = ShiftFactory(capacity=1, starts_at=at(1, 9))
    booking.sign_up(ready(), shift)
    booking.join_waitlist(ready(), shift)
    assert booking.expire_past_waitlists(now=shift.starts_at + timedelta(minutes=1)) == 1


@pytest.mark.parametrize("problem", list(Problem))
def test_every_problem_has_a_plain_explanation(problem):
    result = booking.Result.fail(problem, people=[UserFactory()], reason="needs_orientation")
    text = explain(result, shift=ShiftFactory())
    assert text and not banned_words_in(text)
    assert text != "Something went wrong. Please try again."
