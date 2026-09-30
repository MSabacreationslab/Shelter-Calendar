"""Staff forms for building the schedule."""

from datetime import date, datetime, timedelta

from django import forms
from django.utils import timezone

from core.forms import AccessibleFormMixin
from scheduling.generation import MAX_FILL_WEEKS
from scheduling.models import ShiftKind, TemplateWeek
from training.models import TrainingType

WEEKDAYS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]
REPEAT_CHOICES = [(1, "Every week"), (2, "Every other week")]


def _time_input():
    return forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


def _date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _tick_if_training_needed(form):
    """When editing, the box starts ticked if the shift already needs a training."""
    if "needs_training" not in form.initial:
        form.initial["needs_training"] = bool(form.initial.get("required_training"))


def _clean_training_choice(form, data):
    """Ticked needs a training chosen; unticked means no training, whatever the list says."""
    if data.get("needs_training"):
        if not data.get("required_training"):
            form.add_error("required_training", "Please choose which training this shift needs.")
    else:
        data["required_training"] = None


class ShiftFieldsForm(AccessibleFormMixin, forms.Form):
    """What every shift has: title, times, capacity, and its training rules."""

    title = forms.CharField(
        label="What the shift is",
        max_length=100,
        help_text="For example, Morning dog walking.",
        error_messages={"required": "Please give the shift a name."},
    )
    start_time = forms.TimeField(
        label="Starts",
        widget=_time_input(),
        error_messages={"required": "Please choose a start time."},
    )
    end_time = forms.TimeField(
        label="Ends",
        widget=_time_input(),
        error_messages={"required": "Please choose an end time."},
    )
    capacity = forms.IntegerField(
        label="How many people",
        min_value=1,
        max_value=50,
        initial=2,
        error_messages={"min_value": "At least 1 person, please."},
    )
    kind = forms.ChoiceField(
        label="Type", choices=ShiftKind.choices, initial=ShiftKind.REGULAR, widget=forms.RadioSelect
    )
    needs_training = forms.BooleanField(
        label="This shift needs training",
        required=False,
        help_text="Leave it unticked if anyone who has done orientation can sign up.",
    )
    required_training = forms.ModelChoiceField(
        label="Which training?",
        queryset=TrainingType.objects.none(),
        required=False,
        empty_label="Choose a training",
    )
    teaches = forms.ModelChoiceField(
        label="For a training session: what it teaches",
        queryset=TrainingType.objects.none(),
        required=False,
    )
    notes = forms.CharField(
        label="Notes for volunteers",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="For example, where to meet.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = TrainingType.objects.filter(active=True)
        self.fields["required_training"].queryset = active
        self.fields["teaches"].queryset = active
        _tick_if_training_needed(self)

    def clean(self):
        """End after start; training sessions say what they teach."""
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "The end time needs to be after the start time.")
        if data.get("kind") == ShiftKind.TRAINING:
            if not data.get("teaches"):
                self.add_error("teaches", "Please choose what this session teaches.")
            data["required_training"] = None
            data["needs_training"] = False
        else:
            data["teaches"] = None
            _clean_training_choice(self, data)
        return data

    def model_data(self) -> dict:
        """The cleaned fields a shift or pattern stores (the tick box only guides the form)."""
        return {k: v for k, v in self.cleaned_data.items() if k != "needs_training"}


class PatternForm(ShiftFieldsForm):
    """A repeating shift in a template week. Its day and rhythm are fixed once created."""

    weekday = forms.TypedChoiceField(label="Day", choices=WEEKDAYS, coerce=int)
    every_n_weeks = forms.TypedChoiceField(
        label="How often", choices=REPEAT_CHOICES, coerce=int, initial=1
    )
    active_from = forms.DateField(
        label="Starting from",
        widget=_date_input(),
        initial=timezone.localdate,
        help_text="For every other week, this date's week is the first one.",
    )
    field_order = ["title", "weekday", "start_time", "end_time", "every_n_weeks"]

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        if editing:
            # To move a repeating shift to another day, stop it and add a new one.
            for name in ("weekday", "every_n_weeks", "active_from"):
                del self.fields[name]


class OneOffShiftForm(ShiftFieldsForm):
    """A single shift on one day, optionally repeating weekly until a date."""

    day = forms.DateField(
        label="Date", widget=_date_input(), error_messages={"required": "Please choose a date."}
    )
    repeat_until = forms.DateField(
        label="Repeat every week until",
        required=False,
        widget=_date_input(),
        help_text="Leave blank for just this one day.",
    )
    field_order = ["title", "day", "start_time", "end_time", "repeat_until"]

    def clean(self):
        """The date can't be in the past; repeats end after they start."""
        data = super().clean()
        day, until = data.get("day"), data.get("repeat_until")
        if day and day < timezone.localdate():
            self.add_error("day", "Please choose today or a later date.")
        if day and until:
            if until <= day:
                self.add_error("repeat_until", "The last date needs to be after the first.")
            elif (until - day).days > MAX_FILL_WEEKS * 7:
                self.add_error(
                    "repeat_until", f"Repeat for at most {MAX_FILL_WEEKS} weeks at a time."
                )
        return data

    def shift_data(self) -> dict:
        """Fields for a Shift model."""
        data = self.cleaned_data
        day = data["day"]
        return {
            "title": data["title"],
            "kind": data["kind"],
            "teaches": data["teaches"],
            "required_training": data["required_training"],
            "starts_at": timezone.make_aware(datetime.combine(day, data["start_time"])),
            "ends_at": timezone.make_aware(datetime.combine(day, data["end_time"])),
            "capacity": data["capacity"],
            "notes": data["notes"],
        }

    def pattern_data(self) -> dict:
        """Fields for a standalone ShiftPattern when the shift repeats."""
        data = self.cleaned_data
        return {
            "title": data["title"],
            "weekday": data["day"].weekday(),
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "capacity": data["capacity"],
            "kind": data["kind"],
            "teaches": data["teaches"],
            "required_training": data["required_training"],
            "notes": data["notes"],
            "every_n_weeks": 1,
            "active_from": data["day"],
            "active_until": data["repeat_until"],
        }


class EditShiftForm(AccessibleFormMixin, forms.Form):
    """Change one shift's time, size, training or notes."""

    title = forms.CharField(label="What the shift is", max_length=100)
    start_time = forms.TimeField(label="Starts", widget=_time_input())
    end_time = forms.TimeField(label="Ends", widget=_time_input())
    capacity = forms.IntegerField(label="How many people", min_value=1, max_value=50)
    needs_training = forms.BooleanField(
        label="This shift needs training",
        required=False,
        help_text="Leave it unticked if anyone who has done orientation can sign up.",
    )
    required_training = forms.ModelChoiceField(
        label="Which training?",
        queryset=TrainingType.objects.filter(active=True),
        required=False,
        empty_label="Choose a training",
    )
    notes = forms.CharField(
        label="Notes for volunteers", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, shift=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shift = shift
        if shift and shift.kind == ShiftKind.TRAINING:
            del self.fields["required_training"]
            del self.fields["needs_training"]
        else:
            _tick_if_training_needed(self)

    def clean(self):
        """End after start."""
        data = super().clean()
        if (
            data.get("start_time")
            and data.get("end_time")
            and data["end_time"] <= data["start_time"]
        ):
            self.add_error("end_time", "The end time needs to be after the start time.")
        if "needs_training" in self.fields:
            _clean_training_choice(self, data)
        return data

    def changes(self) -> dict:
        """Fields for services.update_shift."""
        data = self.cleaned_data
        day = self.shift.local_date
        changes = {
            "title": data["title"],
            "starts_at": timezone.make_aware(datetime.combine(day, data["start_time"])),
            "ends_at": timezone.make_aware(datetime.combine(day, data["end_time"])),
            "capacity": data["capacity"],
            "notes": data["notes"],
        }
        if "required_training" in self.fields:
            changes["required_training"] = data["required_training"]
        return changes


class ReasonForm(AccessibleFormMixin, forms.Form):
    """Why a shift is being cancelled (volunteers see this)."""

    reason = forms.CharField(
        label="Why is it cancelled?",
        max_length=200,
        help_text="Volunteers who signed up will see this in their email.",
        error_messages={"required": "Please give a short reason."},
    )


class TemplateWeekForm(AccessibleFormMixin, forms.Form):
    name = forms.CharField(
        label="Name",
        max_length=100,
        help_text="For example, Regular week or Summer.",
        error_messages={"required": "Please give it a name."},
    )

    def clean_name(self):
        """No two template weeks with the same name."""
        name = " ".join(self.cleaned_data["name"].split())
        if TemplateWeek.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"There's already a template week called “{name}”.")
        return name


class FillForm(AccessibleFormMixin, forms.Form):
    """Which weeks to fill in."""

    start = forms.DateField(label="From", widget=_date_input())
    end = forms.DateField(label="To", widget=_date_input())

    def __init__(self, *args, **kwargs):
        today = timezone.localdate()
        kwargs.setdefault("initial", {"start": today, "end": today + timedelta(weeks=4)})
        super().__init__(*args, **kwargs)

    def clean(self):
        """A sensible range, at most 26 weeks, not in the past."""
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and start < timezone.localdate():
            self.add_error("start", "Please start today or later.")
        if start and end:
            if end < start:
                self.add_error("end", "The end date needs to be after the start date.")
            elif (end - start).days > MAX_FILL_WEEKS * 7:
                self.add_error("end", f"Fill at most {MAX_FILL_WEEKS} weeks at a time.")
        return data


class EndPatternForm(AccessibleFormMixin, forms.Form):
    last_day = forms.DateField(
        label="Last day it runs",
        widget=_date_input(),
        help_text="Empty shifts after this date are removed.",
    )

    def clean_last_day(self):
        """Can't end it in the past."""
        day = self.cleaned_data["last_day"]
        if day < timezone.localdate() - timedelta(days=1):
            raise forms.ValidationError("Please choose yesterday or a later date.")
        return day


class BlackoutForm(AccessibleFormMixin, forms.Form):
    start_date = forms.DateField(label="First closed day", widget=_date_input())
    end_date = forms.DateField(
        label="Last closed day", widget=_date_input(), help_text="The same day for a single day."
    )
    reason = forms.CharField(
        label="Why", max_length=200, help_text="For example, Staff training day."
    )

    def clean(self):
        """The last day can't be before the first."""
        data = super().clean()
        if (
            data.get("start_date")
            and data.get("end_date")
            and data["end_date"] < data["start_date"]
        ):
            self.add_error("end_date", "The last day needs to be on or after the first.")
        return data


class HolidayForm(AccessibleFormMixin, forms.Form):
    day = forms.DateField(label="Date", widget=_date_input())
    name = forms.CharField(
        label="Name", max_length=100, help_text="For example, Shelter anniversary."
    )


class AssignForm(AccessibleFormMixin, forms.Form):
    """Staff pick someone to add to a shift."""

    person = forms.ModelChoiceField(
        label="Add someone", queryset=None, empty_label="Choose a person"
    )

    def __init__(self, *args, people=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = people


def week_start(day: date) -> date:
    """The Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


class CancelForm(AccessibleFormMixin, forms.Form):
    """An optional note when a volunteer can't make it."""

    reason = forms.CharField(
        label="Anything you'd like us to know?",
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
