"""Reminders and birthday emails (SPEC §6, Phase 8)."""

import io
from datetime import date, datetime, time, timedelta

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import Status
from notifications import reminders
from notifications.models import SentReminder
from scheduling.models import ShiftStatus, Signup, SignupStatus
from tests.factories import ShiftFactory, UserFactory

pytestmark = pytest.mark.django_db

SUNDAY = date(2027, 1, 3)
MONDAY = date(2027, 1, 4)


def moment(day, hour):
    return timezone.make_aware(datetime.combine(day, time(hour)))


def book(person, day, hour=9, **shift_fields):
    shift = ShiftFactory(starts_at=moment(day, hour), **shift_fields)
    return Signup.objects.create(
        shift=shift, volunteer=person, period=(shift.starts_at, shift.ends_at)
    )


def person_named(first, **kwargs):
    return UserFactory(first_name=first, **kwargs)


# Evening before


def test_one_evening_email_lists_all_of_tomorrows_shifts():
    mary = person_named("Mary")
    book(mary, MONDAY, 9, title="Dog walking", notes="Side door")
    book(mary, MONDAY, 13, title="Cat care")
    assert reminders.send_evening_reminders(SUNDAY) == 1
    message = mail.outbox[0]
    assert message.to == [mary.email]
    assert message.subject == "Reminder: your shifts tomorrow"
    assert "Dog walking" in message.body and "Cat care" in message.body
    assert "Good to know: Side door" in message.body
    assert "&nbsp;" not in message.body


def test_no_reminders_for_cancellations_turned_off_people_or_opt_outs():
    cancelled = book(person_named("Cancelled"), MONDAY)
    Signup.objects.filter(pk=cancelled.pk).update(status=SignupStatus.CANCELLED)
    shift_gone = book(person_named("ShiftGone"), MONDAY)
    shift_gone.shift.status = ShiftStatus.CANCELLED
    shift_gone.shift.save()
    book(person_named("Off", status=Status.INACTIVE), MONDAY)
    book(person_named("NoThanks", profile__wants_reminders=False), MONDAY)
    assert reminders.send_evening_reminders(SUNDAY) == 0
    assert mail.outbox == []


def test_evening_reminders_are_sent_once():
    book(person_named("Mary"), MONDAY)
    assert reminders.send_evening_reminders(SUNDAY) == 1
    assert reminders.send_evening_reminders(SUNDAY) == 0
    assert len(mail.outbox) == 1


# Sunday list for busy weeks


def test_four_or_more_shifts_get_the_sunday_list_instead():
    busy, light = person_named("Busy"), person_named("Light")
    for offset in range(4):
        book(busy, MONDAY + timedelta(days=offset))
    for offset in range(3):
        book(light, MONDAY + timedelta(days=offset))
    lists, evening = reminders.send_reminders(SUNDAY)
    assert (lists, evening) == (1, 1)
    subjects = {m.to[0]: m.subject for m in mail.outbox}
    assert subjects[busy.email].startswith("Your shifts this week")
    assert subjects[light.email] == "Reminder: your shift tomorrow"
    mail.outbox.clear()
    # Tuesday evening: the busy person already had the week's list.
    assert reminders.send_evening_reminders(MONDAY + timedelta(days=1)) == 1
    assert [m.to for m in mail.outbox] == [[light.email]]


def test_the_sunday_list_only_goes_out_on_sundays():
    busy = person_named("Busy")
    for offset in range(5):
        book(busy, MONDAY + timedelta(days=offset))
    assert reminders.send_reminders(SUNDAY - timedelta(days=1))[0] == 0
    assert reminders.send_reminders(SUNDAY)[0] == 1


# Birthdays


def test_birthday_email_on_the_day_and_only_once():
    mary = person_named("Mary", profile__birthday_month=3, profile__birthday_day=14)
    person_named("Other", profile__birthday_month=3, profile__birthday_day=15)
    person_named("Nobirthday")
    assert reminders.send_birthdays(date(2027, 3, 14)) == 1
    assert mail.outbox[0].to == [mary.email]
    assert mail.outbox[0].subject == "Happy birthday, Mary!"
    assert reminders.send_birthdays(date(2027, 3, 14)) == 0


def test_february_29_birthdays_are_celebrated_on_the_28th_in_other_years():
    leapling = person_named("Leap", profile__birthday_month=2, profile__birthday_day=29)
    assert reminders.send_birthdays(date(2027, 2, 28)) == 1
    assert mail.outbox[0].to == [leapling.email]
    assert reminders.send_birthdays(date(2028, 2, 28)) == 0
    assert reminders.send_birthdays(date(2028, 2, 29)) == 1


def test_turned_off_people_get_no_birthday_email():
    person_named("Off", status=Status.INACTIVE, profile__birthday_month=5, profile__birthday_day=1)
    assert reminders.send_birthdays(date(2027, 5, 1)) == 0


# Commands and the profile switch


def test_commands_accept_a_date():
    book(person_named("Mary"), MONDAY)
    person_named("Bday", profile__birthday_month=1, profile__birthday_day=3)
    out = io.StringIO()
    call_command("send_reminders", "--date", SUNDAY.isoformat(), stdout=out)
    assert "1 reminders for tomorrow" in out.getvalue()
    out = io.StringIO()
    call_command("send_birthday_emails", "--date", SUNDAY.isoformat(), stdout=out)
    assert "Sent 1 birthday emails." in out.getvalue()
    assert SentReminder.objects.count() == 2
    with pytest.raises(CommandError):
        call_command("send_reminders", "--date", "tomorrow")


def test_volunteers_turn_reminders_off_on_their_profile(client):
    person = UserFactory(profile__emergency_contact_name="Sam")
    client.force_login(person)
    form = client.get("/profile/").content.decode()
    assert "Email me a reminder before my shifts" in form
    client.post(
        "/profile/",
        {
            "phone": person.phone,
            "emergency_contact_name": "Sam",
            "emergency_contact_phone": "7405550111",
            "emergency_contact_relationship": "",
        },
    )
    person.refresh_from_db()
    assert not person.profile.wants_reminders
    book(person, MONDAY)
    assert reminders.send_evening_reminders(SUNDAY) == 0


def test_all_reminders_go_through_one_delivery_function(monkeypatch):
    calls = []
    monkeypatch.setattr(
        reminders, "deliver", lambda person, template, context: calls.append(template)
    )
    book(person_named("Mary"), MONDAY)
    reminders.send_evening_reminders(SUNDAY)
    assert calls == ["reminder_evening"]
    assert mail.outbox == []
