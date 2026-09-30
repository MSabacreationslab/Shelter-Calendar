"""Sign-in and choose-a-PIN forms."""

from django import forms

from accounts.pins import PIN_LENGTH, pin_problem
from core.forms import AccessibleFormMixin


def _pin_widget(autocomplete):
    """A PIN box that brings up the number pad on phones."""
    return forms.PasswordInput(
        attrs={
            "inputmode": "numeric",
            "autocomplete": autocomplete,
            "maxlength": PIN_LENGTH,
            "class": "pin-input",
            "data-show-pin": "true",
        }
    )


class SignInForm(AccessibleFormMixin, forms.Form):
    """Name and PIN."""

    name = forms.CharField(
        label="Your name",
        max_length=150,
        help_text="Your first and last name, as the shelter has it.",
        error_messages={"required": "Please enter your name."},
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "words", "spellcheck": "false"}
        ),
    )
    pin = forms.CharField(
        label="PIN",
        help_text="Your 6-digit PIN.",
        strip=True,
        error_messages={"required": "Please enter your 6-digit PIN."},
        widget=_pin_widget("current-password"),
    )


class SetPinForm(AccessibleFormMixin, forms.Form):
    """Choose a PIN and type it again."""

    pin = forms.CharField(
        label="Choose a 6-digit PIN",
        help_text="Pick 6 numbers you'll remember. Avoid patterns like 123456.",
        error_messages={"required": "Please choose a 6-digit PIN."},
        widget=_pin_widget("new-password"),
    )
    pin_again = forms.CharField(
        label="Type your PIN again",
        error_messages={"required": "Please type your PIN a second time."},
        widget=_pin_widget("new-password"),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_pin(self):
        """Apply the PIN rules, including not using the end of their phone number."""
        pin = self.cleaned_data["pin"]
        problem = pin_problem(pin, phone=self.user.phone if self.user else "")
        if problem:
            raise forms.ValidationError(problem)
        return pin

    def clean(self):
        """Both boxes must match."""
        data = super().clean()
        if data.get("pin") and data.get("pin_again") and data["pin"] != data["pin_again"]:
            self.add_error("pin_again", "The two PINs don't match. Please type them again.")
        return data
