"""Staff forms for training records and the list of trainings."""

from django import forms
from django.utils import timezone

from accounts.models import Role, Status, User
from core.forms import AccessibleFormMixin
from training.models import TrainingType


def _date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class PersonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, person):
        """Full name, plus job title for staff."""
        name = person.get_full_name()
        return f"{name} ({person.job_title})" if person.job_title else name


class PeopleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, person):
        """Full name."""
        return person.get_full_name()


def active_people():
    """Everyone who can be trained: active volunteers and staff (never the Admin)."""
    return User.objects.filter(
        status=Status.ACTIVE, role__in=[Role.VOLUNTEER, Role.STAFF]
    ).order_by("first_name", "last_name")


def trainers():
    """Staff and the Admin, who can lead and sign off training."""
    return User.objects.filter(status=Status.ACTIVE, role__in=[Role.STAFF, Role.ADMIN]).order_by(
        "first_name", "last_name"
    )


class _CompletedOnMixin:
    def clean_completed_on(self):
        """Training can't be finished in the future."""
        day = self.cleaned_data["completed_on"]
        if day > timezone.localdate():
            raise forms.ValidationError("Please choose today or an earlier date.")
        return day


class AttendanceForm(_CompletedOnMixin, AccessibleFormMixin, forms.Form):
    """Who came to a training session. Signed-up people start ticked."""

    attended = PeopleChoiceField(
        label="Who came and finished it",
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Untick anyone who didn't come.",
    )
    also_came = PersonChoiceField(
        label="Someone else who came",
        queryset=User.objects.none(),
        required=False,
        empty_label="Nobody else",
    )
    completed_on = forms.DateField(label="Date", widget=_date_input())
    trainer = PersonChoiceField(
        label="Who led it", queryset=User.objects.none(), required=False, empty_label="Not recorded"
    )
    notes = forms.CharField(label="Notes", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, candidates=None, others=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attended"].queryset = candidates
        self.fields["also_came"].queryset = others
        self.fields["trainer"].queryset = trainers()

    def clean(self):
        """At least one person, or there's nothing to save."""
        data = super().clean()
        if not data.get("attended") and not data.get("also_came"):
            raise forms.ValidationError("Please tick at least one person who came.")
        return data

    def people(self) -> list[User]:
        """Everyone to record, without repeats."""
        chosen = list(self.cleaned_data.get("attended") or [])
        extra = self.cleaned_data.get("also_came")
        if extra and extra not in chosen:
            chosen.append(extra)
        return chosen


class RecordForm(_CompletedOnMixin, AccessibleFormMixin, forms.Form):
    """One training someone did outside a session in the app."""

    person = PersonChoiceField(
        label="Who", queryset=User.objects.none(), empty_label="Choose a person"
    )
    training_type = forms.ModelChoiceField(
        label="Which training",
        queryset=TrainingType.objects.none(),
        empty_label="Choose a training",
    )
    completed_on = forms.DateField(label="When they finished it", widget=_date_input())
    trainer = PersonChoiceField(
        label="Who led it", queryset=User.objects.none(), required=False, empty_label="Not recorded"
    )
    notes = forms.CharField(label="Notes", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = active_people()
        self.fields["training_type"].queryset = TrainingType.objects.filter(active=True)
        self.fields["trainer"].queryset = trainers()


class VoidForm(AccessibleFormMixin, forms.Form):
    reason = forms.CharField(
        label="What was wrong with it?",
        max_length=200,
        help_text="For example, recorded for the wrong person.",
        error_messages={"required": "Please give a short reason."},
    )


class NeedForm(AccessibleFormMixin, forms.Form):
    training_type = forms.ModelChoiceField(
        label="Add a training they need",
        queryset=TrainingType.objects.none(),
        empty_label="Choose a training",
    )

    def __init__(self, *args, person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["training_type"].queryset = TrainingType.objects.filter(active=True)


class TrainingTypeForm(AccessibleFormMixin, forms.Form):
    """Add or rename a training."""

    name = forms.CharField(
        label="Training", max_length=100, error_messages={"required": "Please enter a name."}
    )
    is_orientation = forms.BooleanField(
        label="This is the orientation everyone does first",
        required=False,
        help_text="Finishing orientation lets someone sign up for shifts that need no training.",
    )

    def __init__(self, *args, training_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.training_type = training_type
        has_orientation = TrainingType.objects.filter(is_orientation=True).exists()
        if training_type is not None or has_orientation:
            del self.fields["is_orientation"]

    def clean_name(self):
        """No two trainings with the same name."""
        name = " ".join(self.cleaned_data["name"].split())
        clash = TrainingType.objects.filter(name__iexact=name)
        if self.training_type:
            clash = clash.exclude(pk=self.training_type.pk)
        if clash.exists():
            raise forms.ValidationError(f"“{name}” is already on the list.")
        return name
