from smtplib import SMTPException

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives

from accounts.models import Role, SetupLink, Skill, Status, User
from core.models import AuditEvent
from notifications.models import EmailLog
from tests.factories import AdminFactory, TrainingTypeFactory, UserFactory
from training.models import TrainingNeed

pytestmark = pytest.mark.django_db


def _form(**overrides):
    data = {
        "first_name": "Mary",
        "last_name": "Smith",
        "email": "mary@example.com",
        "phone": "(740) 555-0142",
        "emergency_contact_name": "John Smith",
        "emergency_contact_phone": "740.555.0199",
        "emergency_contact_relationship": "Husband",
        "birthday_month": "3",
        "birthday_day": "14",
        "staff_notes": "",
        "login_name": "",
    }
    data.update(overrides)
    return data


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def post(staff_client, django_capture_on_commit_callbacks):
    """POST as staff, then run the after-save steps (the emails) as they run for real."""

    def send(path, data=None, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return staff_client.post(path, data or {}, **kwargs)

    return send


def test_adding_a_volunteer_creates_everything_and_sends_the_welcome(post, staff):
    orientation = TrainingTypeFactory(name="Orientation", is_orientation=True)
    skill = Skill.objects.get(name="Dog walking")
    response = post(
        "/volunteers/add/",
        _form(skills=[skill.pk], trainings_needed=[orientation.pk], no_training_eligible="on"),
    )
    person = User.objects.get(login_name="Mary Smith")
    assert response["Location"] == f"/volunteers/{person.pk}/"
    assert person.role == Role.VOLUNTEER
    assert person.phone == "7405550142"
    assert not person.has_usable_password()
    profile = person.profile
    assert profile.emergency_contact_phone == "7405550199"
    assert (profile.birthday_month, profile.birthday_day) == (3, 14)
    assert profile.no_training_eligible
    assert profile.added_by == staff
    assert list(profile.skills.all()) == [skill]
    assert TrainingNeed.objects.filter(
        volunteer=person, training_type=orientation, resolved_at__isnull=True
    ).exists()
    assert AuditEvent.objects.filter(
        action="account.created", actor=staff, target_user=person
    ).exists()
    assert len(mail.outbox) == 1
    welcome = mail.outbox[0]
    assert welcome.to == ["mary@example.com"]
    assert "Mary Smith" in welcome.body
    assert "/welcome/" in welcome.body
    assert welcome.alternatives
    assert EmailLog.objects.get(related_user=person).sent_at is not None


def test_required_fields_have_plain_messages(staff_client):
    html = staff_client.post("/volunteers/add/", {}).content.decode()
    for message in ["Please enter a first name.", "Please enter an email address."]:
        assert message in html
    assert not User.objects.filter(role=Role.VOLUNTEER).exists()


def test_phone_numbers_are_accepted_however_they_are_typed(post):
    post("/volunteers/add/", _form(phone="+1 740 555 0142"))
    assert User.objects.get(login_name="Mary Smith").phone == "7405550142"


def test_short_phone_numbers_are_explained(staff_client):
    html = staff_client.post("/volunteers/add/", _form(phone="555-0142")).content.decode()
    assert "10-digit phone number" in html


@pytest.mark.parametrize(
    ("month", "day", "message"),
    [("2", "30", "February doesn&#x27;t have 30 days."), ("2", "", "both a month and a day")],
)
def test_birthdays_must_be_real_dates(staff_client, month, day, message):
    html = staff_client.post(
        "/volunteers/add/", _form(birthday_month=month, birthday_day=day)
    ).content.decode()
    assert message in html


def test_february_29_birthdays_are_fine(post):
    post("/volunteers/add/", _form(birthday_month="2", birthday_day="29"))
    assert User.objects.get(login_name="Mary Smith").profile.birthday_day == 29


def test_a_taken_sign_in_name_asks_for_a_variant(post):
    UserFactory(first_name="Mary", last_name="Smith", email="other@example.com", phone="1112223333")
    html = post("/volunteers/add/", _form()).content.decode()
    assert "already signs in as" in html
    post("/volunteers/add/", _form(login_name="Mary Smith B"))
    assert User.objects.filter(login_name="Mary Smith B").exists()


def test_possible_duplicates_need_a_second_yes(post):
    UserFactory(first_name="Maria", last_name="Smyth", email="mary@example.com")
    first = post("/volunteers/add/", _form())
    assert "might be someone who's already here" in first.content.decode()
    assert not User.objects.filter(login_name="Mary Smith").exists()
    post("/volunteers/add/", _form(add_anyway="1"))
    assert User.objects.filter(login_name="Mary Smith").exists()


def test_a_failed_email_keeps_the_person_and_warns_staff(post, staff_client, monkeypatch):
    def fail(self, *args, **kwargs):
        raise SMTPException("mail server said no")

    monkeypatch.setattr(EmailMultiAlternatives, "send", fail)
    post("/volunteers/add/", _form())
    person = User.objects.get(login_name="Mary Smith")
    log = EmailLog.objects.get(related_user=person)
    assert log.failed and "mail server said no" in log.error
    page = staff_client.get(f"/volunteers/{person.pk}/")
    assert "didn't go through" in page.content.decode()


def test_email_text_keeps_apostrophes(post):
    post("/volunteers/add/", _form(first_name="Pat", last_name="O'Brien"))
    assert "Pat O'Brien" in mail.outbox[0].body
    assert "&#x27;" not in mail.outbox[0].body


def test_new_link_replaces_the_old_one_and_matches_the_situation(post):
    newcomer = UserFactory()
    newcomer.set_unusable_password()
    newcomer.save()
    post(f"/volunteers/{newcomer.pk}/new-link/")
    post(f"/volunteers/{newcomer.pk}/new-link/")
    links = SetupLink.objects.filter(user=newcomer)
    assert links.count() == 2
    assert links.filter(voided_at__isnull=True).count() == 1
    assert "Welcome" in mail.outbox[-1].subject

    regular = UserFactory()
    post(f"/volunteers/{regular.pk}/new-link/")
    assert mail.outbox[-1].subject == "Your link to choose a new PIN"


def test_the_admin_never_appears_in_staff_screens(staff_client):
    admin = AdminFactory()
    assert staff_client.get(f"/volunteers/{admin.pk}/").status_code == 404
    assert staff_client.post(f"/volunteers/{admin.pk}/new-link/").status_code == 404


def test_editing_logs_which_fields_changed_but_not_their_values(staff_client, staff):
    person = UserFactory(phone="7405550100")
    person.profile.emergency_contact_name = "Sam"
    person.profile.emergency_contact_phone = "7405550111"
    person.profile.save()
    data = _form(
        first_name=person.first_name,
        last_name=person.last_name,
        email=person.email,
        phone="740-555-0177",
        emergency_contact_name="Sam",
        emergency_contact_phone="7405550111",
        emergency_contact_relationship="",
        birthday_month="",
        birthday_day="",
    )
    response = staff_client.post(f"/volunteers/{person.pk}/edit/", data)
    assert response["Location"] == f"/volunteers/{person.pk}/"
    person.refresh_from_db()
    assert person.phone == "7405550177"
    event = AuditEvent.objects.get(action="volunteer.edited", target_user=person)
    assert event.actor == staff
    assert event.details == {"fields": ["phone"]}


def test_list_shows_active_volunteers_unless_asked(staff_client):
    active = UserFactory(first_name="Active")
    gone = UserFactory(first_name="Gone", status=Status.INACTIVE)
    html = staff_client.get("/volunteers/").content.decode()
    assert active.get_full_name() in html and gone.get_full_name() not in html
    html = staff_client.get("/volunteers/?show=all").content.decode()
    assert gone.get_full_name() in html


def test_skills_can_be_added_renamed_and_taken_off_the_list(staff_client, staff):
    staff_client.post("/skills/", {"name": "Laundry"})
    laundry = Skill.objects.get(name="Laundry")
    duplicate = staff_client.post("/skills/", {"name": "laundry"}).content.decode()
    assert "already on the list" in duplicate
    staff_client.post(f"/skills/{laundry.pk}/", {"name": "Laundry and dishes"})
    staff_client.post(f"/skills/{laundry.pk}/toggle/")
    laundry.refresh_from_db()
    assert laundry.name == "Laundry and dishes" and not laundry.active
    actions = set(AuditEvent.objects.filter(actor=staff).values_list("action", flat=True))
    assert {"skill.added", "skill.renamed", "skill.turned_off"} <= actions


def test_empty_form_posts_still_show_errors(client):
    html = client.post("/sign-in/", {}).content.decode()
    assert "Please enter your name." in html
