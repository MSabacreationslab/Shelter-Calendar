"""Forms for the change log and the Admin's shelter settings."""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts.models import User
from core.forms import AccessibleFormMixin


def _date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ChangeLogFilterForm(forms.Form):
    person = forms.ModelChoiceField(
        label="About", required=False, queryset=User.objects.none(), empty_label="Anyone"
    )
    start = forms.DateField(label="From", required=False, widget=_date_input())
    end = forms.DateField(label="To", required=False, widget=_date_input())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = User.objects.order_by("first_name", "last_name")
        self.fields["person"].label_from_instance = lambda p: p.get_full_name()


class SettingsForm(AccessibleFormMixin, forms.Form):
    shelter_name = forms.CharField(label="Shelter name", max_length=200)
    shelter_phone = forms.CharField(
        label="Shelter phone",
        max_length=30,
        required=False,
        help_text="Shown on every page and in emails, e.g. (740) 555-0100.",
    )
    shelter_email = forms.EmailField(label="Shelter email", required=False)
    self_cancel_hours = forms.TypedChoiceField(
        label="Volunteers can cancel on their own until",
        coerce=int,
        choices=[(12, "12 hours before"), (24, "24 hours before"), (48, "48 hours before")],
        help_text="Closer than this, the button says “I can't make it”.",
    )
    urgent_threshold_hours = forms.TypedChoiceField(
        label="A cancellation is urgent when it's less than",
        coerce=int,
        choices=[
            (24, "24 hours before the shift"),
            (48, "48 hours before the shift"),
            (72, "72 hours before the shift"),
        ],
        help_text="Urgent cancellations email the notify list straight away.",
    )
    notify_emails = forms.CharField(
        label="Staff who get notification emails",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One email address per line.",
    )

    def clean_notify_emails(self):
        """Every line must be an email address."""
        lines = [line.strip() for line in self.cleaned_data["notify_emails"].splitlines()]
        lines = [line for line in lines if line]
        for line in lines:
            try:
                validate_email(line)
            except ValidationError as exc:
                raise forms.ValidationError(
                    f"“{line}” doesn't look like an email address."
                ) from exc
        return "\n".join(lines)
