"""Form helpers shared by every app."""

from django import forms


def post_data(request):
    """The submitted data on a POST, else None. Unlike `request.POST or None`, an empty
    POST still counts as submitted, so its errors are shown."""
    return request.POST if request.method == "POST" else None


class AccessibleFormMixin:
    """Link each input to its hint and error text so screen readers announce them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if field.help_text:
                field.widget.attrs["aria-describedby"] = f"{self[name].auto_id}_hint"

    def full_clean(self):
        """Mark fields with errors as invalid and point them at their error message."""
        super().full_clean()
        for name in self.errors:
            if name not in self.fields:
                continue
            attrs = self.fields[name].widget.attrs
            ids = [attrs.get("aria-describedby", ""), f"{self[name].auto_id}_error"]
            attrs["aria-describedby"] = " ".join(i for i in ids if i)
            attrs["aria-invalid"] = "true"


class StyleguideForm(AccessibleFormMixin, forms.Form):
    """A sample form for the style guide, so field states can be checked by eye."""

    name = forms.CharField(label="Your name", help_text="The name you use at the shelter.")
    phone = forms.CharField(
        label="Phone number",
        help_text="We only call about your shifts.",
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}),
    )
    notes = forms.CharField(label="Anything we should know?", required=False)

    def clean_phone(self):
        """Accept any 10-digit US phone number, however it's typed."""
        digits = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())
        if len(digits) != 10:
            raise forms.ValidationError("Please enter a 10-digit phone number.")
        return digits
