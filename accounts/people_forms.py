"""Staff forms for adding and editing volunteers (SPEC §6, Phase 2)."""

import calendar

from django import forms
from django.db.models import Count, F, Q
from django.utils import timezone

from accounts.models import Skill, User, normalize_login_name
from core.forms import AccessibleFormMixin
from core.phones import normalize_phone
from core.templatetags.formatting import MONTHS, clock_text, long_date
from scheduling.models import Shift, ShiftKind, ShiftStatus, SignupStatus
from training.models import TrainingType

MONTH_CHOICES = [("", "Month")] + [(str(i), name) for i, name in enumerate(MONTHS, start=1)]
DAY_CHOICES = [("", "Day")] + [(str(d), str(d)) for d in range(1, 32)]


class PhoneField(forms.CharField):
    """Accepts a US number typed any way; cleans to 10 digits."""

    def __init__(self, **kwargs):
        kwargs.setdefault(
            "widget", forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"})
        )
        super().__init__(**kwargs)

    def clean(self, value):
        """Normalize, or explain the expected format."""
        value = super().clean(value)
        if not value:
            return value
        try:
            return normalize_phone(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class VolunteerDetailsForm(AccessibleFormMixin, forms.Form):
    """Everything staff record about a volunteer."""

    first_name = forms.CharField(
        label="First name",
        max_length=150,
        error_messages={"required": "Please enter a first name."},
    )
    last_name = forms.CharField(
        label="Last name", max_length=150, error_messages={"required": "Please enter a last name."}
    )
    email = forms.EmailField(
        label="Email",
        help_text="The welcome email with their PIN link goes here.",
        error_messages={
            "required": "Please enter an email address.",
            "invalid": "Please check the email address; it should look like name@example.com.",
        },
    )
    phone = PhoneField(label="Phone", error_messages={"required": "Please enter a phone number."})
    emergency_contact_name = forms.CharField(
        label="Emergency contact's name",
        max_length=150,
        error_messages={"required": "Please enter an emergency contact."},
    )
    emergency_contact_phone = PhoneField(
        label="Emergency contact's phone",
        error_messages={"required": "Please enter the emergency contact's phone."},
    )
    emergency_contact_relationship = forms.CharField(
        label="How they're related", max_length=60, required=False, help_text="For example, wife."
    )
    birthday_month = forms.ChoiceField(
        label="Birthday month", choices=MONTH_CHOICES, required=False
    )
    birthday_day = forms.ChoiceField(label="Birthday day", choices=DAY_CHOICES, required=False)
    skills = forms.ModelMultipleChoiceField(
        label="What they'd like to help with",
        queryset=Skill.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    staff_notes = forms.CharField(
        label="Notes for staff",
        required=False,
        help_text="Only staff see these.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.person = person
        self.fields["skills"].queryset = Skill.objects.filter(active=True)

    def clean(self):
        """A birthday needs both parts and has to be a real date (Feb 29 is allowed)."""
        data = super().clean()
        month, day = data.get("birthday_month"), data.get("birthday_day")
        if bool(month) != bool(day):
            self.add_error("birthday_day", "Please choose both a month and a day, or neither.")
        elif month and day:
            if int(day) > calendar.monthrange(2024, int(month))[1]:
                self.add_error("birthday_day", f"{MONTHS[int(month) - 1]} doesn't have {day} days.")
        return data

    def possible_duplicates(self):
        """Other people with the same email or phone (a warning, not a block)."""
        email, phone = self.cleaned_data.get("email"), self.cleaned_data.get("phone")
        matches = User.objects.filter(Q(email__iexact=email) | Q(phone=phone))
        if self.person:
            matches = matches.exclude(pk=self.person.pk)
        return list(matches[:5])


def upcoming_orientations():
    """Orientation sessions that haven't started and still have space."""
    return (
        Shift.objects.filter(
            kind=ShiftKind.TRAINING,
            teaches__is_orientation=True,
            status=ShiftStatus.SCHEDULED,
            starts_at__gt=timezone.now(),
        )
        .annotate(filled=Count("signups", filter=Q(signups__status=SignupStatus.CONFIRMED)))
        .filter(filled__lt=F("capacity"))
        .select_related("teaches")
        .order_by("starts_at")
    )


class OrientationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, shift):
        """Tuesday, October 6 at 10:00 AM (4 spots left)."""
        spots = shift.capacity - shift.filled
        return (
            f"{long_date(shift.starts_at)} at {clock_text(shift.starts_at)} "
            f"({spots} spot{'s' if spots != 1 else ''} left)"
        )


class AddVolunteerForm(VolunteerDetailsForm):
    """Adding someone after the shelter's paperwork is done."""

    login_name = forms.CharField(
        label="Sign-in name",
        max_length=150,
        required=False,
        help_text="Leave blank to use their first and last name.",
    )
    no_training_eligible = forms.BooleanField(
        label="Can sign up for shifts that need no training, starting now", required=False
    )
    trainings_needed = forms.ModelMultipleChoiceField(
        label="Trainings they need",
        queryset=TrainingType.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    orientation = OrientationChoiceField(
        label="Orientation session",
        queryset=Shift.objects.none(),
        required=False,
        empty_label="Not yet: book it later",
        help_text="The welcome email includes it, with a link if the time doesn't work.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["trainings_needed"].queryset = TrainingType.objects.filter(active=True)
        self.fields["orientation"].queryset = upcoming_orientations()

    def clean(self):
        """Pick the sign-in name and make sure nobody else uses it."""
        data = super().clean()
        if data.get("first_name") and data.get("last_name"):
            chosen = data.get("login_name") or f"{data['first_name']} {data['last_name']}"
            chosen = normalize_login_name(chosen)
            if User.objects.filter(login_name__iexact=chosen).exists():
                self.add_error(
                    "login_name",
                    f"Someone already signs in as “{chosen}”. Please add something to tell "
                    "them apart, like a middle initial.",
                )
            data["login_name"] = chosen
        return data


def details_initial(person) -> dict:
    """Current values for the edit form."""
    profile = person.profile
    return {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "email": person.email,
        "phone": person.phone,
        "emergency_contact_name": profile.emergency_contact_name,
        "emergency_contact_phone": profile.emergency_contact_phone,
        "emergency_contact_relationship": profile.emergency_contact_relationship,
        "birthday_month": profile.birthday_month or "",
        "birthday_day": profile.birthday_day or "",
        "skills": list(profile.skills.all()),
        "staff_notes": profile.staff_notes,
    }


class SkillForm(AccessibleFormMixin, forms.Form):
    """Add or rename a skill."""

    name = forms.CharField(
        label="Skill", max_length=100, error_messages={"required": "Please enter a name."}
    )

    def __init__(self, *args, skill=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill = skill

    def clean_name(self):
        """No two skills with the same name."""
        name = " ".join(self.cleaned_data["name"].split())
        clash = Skill.objects.filter(name__iexact=name)
        if self.skill:
            clash = clash.exclude(pk=self.skill.pk)
        if clash.exists():
            raise forms.ValidationError(f"“{name}” is already on the list.")
        return name
