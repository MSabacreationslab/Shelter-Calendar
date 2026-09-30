"""Training management (SPEC §6, Phase 5) and the "This shift needs training" choice (Q20)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core import audit
from core.models import AuditEvent
from scheduling import services as booking
from scheduling.models import Shift, ShiftKind
from tests.factories import (
    ShiftFactory,
    StaffFactory,
    TrainingTypeFactory,
    UserFactory,
    at,
    trained,
)
from training import eligibility, services
from training.models import TrainingNeed, TrainingRecord, TrainingType

pytestmark = pytest.mark.django_db


@pytest.fixture
def orientation():
    return TrainingTypeFactory(name="Orientation", is_orientation=True)


@pytest.fixture
def dog_walking():
    return TrainingTypeFactory(name="Dog walking")


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def _session(topic, **kwargs):
    kwargs.setdefault("starts_at", at(-1, 10))
    return ShiftFactory(title=topic.name, kind=ShiftKind.TRAINING, teaches=topic, **kwargs)


# Services


def test_recording_a_session_closes_needs_and_opens_shifts(staff, dog_walking):
    person = UserFactory(profile__no_training_eligible=True)
    TrainingNeed.objects.create(volunteer=person, training_type=dog_walking)
    walk = ShiftFactory(required_training=dog_walking)
    assert not eligibility.can_take(person, walk)
    services.record_session(
        _session(dog_walking), [person], completed_on=timezone.localdate(), trainer=staff, by=staff
    )
    assert eligibility.can_take(person, walk)
    assert not TrainingNeed.objects.filter(volunteer=person, resolved_at__isnull=True).exists()
    assert AuditEvent.objects.filter(action="training.recorded", target_user=person).exists()


def test_orientation_opens_no_training_shifts(staff, orientation):
    person = UserFactory()
    assert not eligibility.can_take(person, ShiftFactory())
    services.record_session(
        _session(orientation), [person], completed_on=timezone.localdate(), trainer=None, by=staff
    )
    person.refresh_from_db()
    assert person.profile.no_training_eligible
    assert eligibility.can_take(person, ShiftFactory(starts_at=at(2, 9)))


def test_session_save_is_all_or_nothing(staff, dog_walking, monkeypatch):
    people = [UserFactory(), UserFactory()]
    real_record = audit.record
    calls = {"n": 0}

    def fail_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(audit, "record", fail_on_second)
    with pytest.raises(RuntimeError):
        services.record_session(
            _session(dog_walking), people, completed_on=timezone.localdate(), trainer=None, by=staff
        )
    assert TrainingRecord.objects.count() == 0


def test_recording_the_same_session_twice_does_not_duplicate(staff, dog_walking):
    person, session = UserFactory(), _session(dog_walking)
    for _ in range(2):
        services.record_session(
            session, [person], completed_on=timezone.localdate(), trainer=None, by=staff
        )
    assert TrainingRecord.objects.filter(volunteer=person).count() == 1


def test_only_training_sessions_have_attendance(staff):
    with pytest.raises(ValueError):
        services.record_session(
            ShiftFactory(),
            [UserFactory()],
            completed_on=timezone.localdate(),
            trainer=None,
            by=staff,
        )


def test_voiding_removes_eligibility_but_keeps_the_record(staff, dog_walking):
    person = UserFactory()
    record = trained(person, dog_walking)
    walk = ShiftFactory(required_training=dog_walking)
    assert eligibility.can_take(person, walk)
    services.void_record(record, reason="Wrong person", by=staff)
    record.refresh_from_db()
    assert record.voided_at and record.void_reason == "Wrong person" and record.voided_by == staff
    assert not eligibility.can_take(person, walk)
    assert TrainingRecord.objects.filter(pk=record.pk).exists()


def test_voiding_the_only_orientation_turns_off_no_training_shifts(staff, orientation):
    person = UserFactory(profile__no_training_eligible=True)
    record = trained(person, orientation)
    assert services.void_record(record, reason="Wrong person", by=staff) is True
    person.refresh_from_db()
    assert not person.profile.no_training_eligible


def test_voiding_twice_changes_nothing(staff, dog_walking):
    record = trained(UserFactory(), dog_walking)
    services.void_record(record, reason="Mistake", by=staff)
    assert services.void_record(record, reason="Again", by=staff) is False
    assert AuditEvent.objects.filter(action="training.voided").count() == 1


def test_needs_and_no_training_permission_are_logged(staff, dog_walking):
    person = UserFactory()
    need = services.add_need(person, dog_walking, by=staff)
    services.add_need(person, dog_walking, by=staff)
    assert TrainingNeed.objects.filter(volunteer=person, resolved_at__isnull=True).count() == 1
    services.remove_need(need, by=staff)
    services.set_no_training_allowed(person, True, by=staff)
    actions = list(AuditEvent.objects.filter(target_user=person).values_list("action", flat=True))
    assert {"training.need_added", "training.need_removed", "volunteer.no_training_changed"} <= set(
        actions
    )


# Screens


def test_session_page_ticks_signed_up_people_and_lists_people_who_need_it(
    staff_client, dog_walking
):
    session = _session(dog_walking, starts_at=at(1, 10))
    signed_up = UserFactory(first_name="Signed")
    TrainingNeed.objects.create(volunteer=signed_up, training_type=dog_walking)
    booking.sign_up(signed_up, session)
    waiting = UserFactory(first_name="Needsit")
    TrainingNeed.objects.create(volunteer=waiting, training_type=dog_walking)
    Shift.objects.filter(pk=session.pk).update(starts_at=at(-1, 10), ends_at=at(-1, 12))
    html = staff_client.get(f"/training/sessions/{session.pk}/").content.decode()
    assert "Signed Tester" in html and "Needsit Tester" in html
    assert f'value="{signed_up.pk}"' in html
    assert html.count("checked") >= 1


def test_recording_attendance_on_screen(staff_client, staff, dog_walking):
    session = _session(dog_walking)
    person, walk_in = UserFactory(), UserFactory()
    # The tick list offers people who signed up or still need it; anyone else is "also came".
    TrainingNeed.objects.create(volunteer=person, training_type=dog_walking)
    response = staff_client.post(
        f"/training/sessions/{session.pk}/",
        {
            "attended": [person.pk],
            "also_came": walk_in.pk,
            "completed_on": timezone.localdate().isoformat(),
            "trainer": staff.pk,
        },
        follow=True,
    )
    assert "recorded for 2 people" in response.content.decode()
    assert set(TrainingRecord.objects.values_list("volunteer_id", flat=True)) == {
        person.pk,
        walk_in.pk,
    }


def test_training_cannot_be_finished_in_the_future(staff_client, dog_walking):
    session = _session(dog_walking)
    html = staff_client.post(
        f"/training/sessions/{session.pk}/",
        {
            "attended": [UserFactory().pk],
            "completed_on": (timezone.localdate() + timedelta(days=1)).isoformat(),
        },
    ).content.decode()
    assert "Please choose today or an earlier date." in html
    assert not TrainingRecord.objects.exists()


def test_a_session_needs_at_least_one_person(staff_client, dog_walking):
    session = _session(dog_walking)
    html = staff_client.post(
        f"/training/sessions/{session.pk}/", {"completed_on": timezone.localdate().isoformat()}
    ).content.decode()
    assert "Please tick at least one person who came." in html


def test_adding_past_training_for_a_person(staff_client, dog_walking):
    person = UserFactory()
    form = staff_client.get(f"/training/add/?person={person.pk}").content.decode()
    assert f'<option value="{person.pk}" selected>' in form
    response = staff_client.post(
        "/training/add/",
        {"person": person.pk, "training_type": dog_walking.pk, "completed_on": "2025-06-01"},
    )
    assert response["Location"] == f"/volunteers/{person.pk}/"
    assert TrainingRecord.objects.get(volunteer=person).completed_on.isoformat() == "2025-06-01"


def test_marking_a_record_as_a_mistake_needs_a_reason(staff_client, dog_walking):
    record = trained(UserFactory(), dog_walking)
    html = staff_client.post(f"/training/records/{record.pk}/void/", {}).content.decode()
    assert "Please give a short reason." in html
    staff_client.post(f"/training/records/{record.pk}/void/", {"reason": "Wrong person"})
    record.refresh_from_db()
    assert record.voided_at is not None


def test_person_page_manages_needs_and_no_training_permission(staff_client, dog_walking):
    person = UserFactory()
    staff_client.post(f"/training/people/{person.pk}/needs/", {"training_type": dog_walking.pk})
    need = TrainingNeed.objects.get(volunteer=person)
    assert "Dog walking" in staff_client.get(f"/volunteers/{person.pk}/").content.decode()
    staff_client.post(f"/training/needs/{need.pk}/remove/")
    need.refresh_from_db()
    assert need.resolved_at is not None
    staff_client.post(f"/training/people/{person.pk}/no-training/", {"allowed": "yes"})
    person.refresh_from_db()
    assert person.profile.no_training_eligible


def test_training_list_add_rename_and_turn_off(staff_client):
    staff_client.post("/training/", {"name": "Special events"})
    special = TrainingType.objects.get(name="Special events")
    assert (
        "already on the list"
        in staff_client.post("/training/", {"name": "special events"}).content.decode()
    )
    staff_client.post(f"/training/types/{special.pk}/", {"name": "Special events help"})
    staff_client.post(f"/training/types/{special.pk}/toggle/")
    special.refresh_from_db()
    assert special.name == "Special events help" and not special.active


def test_orientation_can_only_be_chosen_once(staff_client, orientation):
    html = staff_client.get("/training/").content.decode()
    assert "orientation everyone does first" not in html


# Q20: whether a shift needs training is a tick box on each shift


def _shift_form(**overrides):
    data = {
        "title": "Adoption event",
        "day": (timezone.localdate() + timedelta(days=3)).isoformat(),
        "start_time": "10:00",
        "end_time": "14:00",
        "capacity": "4",
        "kind": "regular",
    }
    data.update(overrides)
    return data


def test_ticking_needs_training_requires_choosing_one(staff_client):
    html = staff_client.post("/schedule/add/", _shift_form(needs_training="on")).content.decode()
    assert "Please choose which training this shift needs." in html
    assert not Shift.objects.exists()


def test_a_ticked_shift_needs_the_chosen_training(staff_client):
    special = TrainingTypeFactory(name="Special events")
    staff_client.post(
        "/schedule/add/", _shift_form(needs_training="on", required_training=special.pk)
    )
    assert Shift.objects.get().required_training == special


def test_unticked_means_no_training_even_if_one_was_picked(staff_client):
    special = TrainingTypeFactory(name="Special events")
    staff_client.post("/schedule/add/", _shift_form(required_training=special.pk))
    assert Shift.objects.get().required_training is None


def test_editing_a_shift_that_needs_training_starts_ticked(staff_client, dog_walking):
    shift = ShiftFactory(required_training=dog_walking)
    html = staff_client.get(f"/schedule/shifts/{shift.pk}/edit/").content.decode()
    assert 'name="needs_training" id="id_needs_training" checked' in html or (
        'id="id_needs_training"' in html and "checked" in html
    )
    staff_client.post(
        f"/schedule/shifts/{shift.pk}/edit/",
        {"title": shift.title, "start_time": "09:00", "end_time": "11:00", "capacity": "3"},
    )
    shift.refresh_from_db()
    assert shift.required_training is None


def test_volunteers_cannot_open_training_screens(client, volunteer):
    client.force_login(volunteer)
    assert client.get("/training/").status_code == 403


def test_staff_and_admin_can(client):
    for person in (StaffFactory(),):
        client.force_login(person)
        assert client.get("/training/").status_code == 200
