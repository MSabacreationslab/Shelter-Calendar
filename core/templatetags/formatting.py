"""Display helpers so dates, times and phone numbers read the same everywhere (SPEC §7)."""

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

from core.phones import format_phone

register = template.Library()

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


@register.filter
def phone(digits):
    """(740) 555-0100."""
    return format_phone(digits)


@register.filter
def tel(digits):
    """Digits for a tel: link."""
    return "".join(ch for ch in digits or "" if ch.isdigit())


@register.filter
def long_date(value):
    """Tuesday, October 6: always with the weekday."""
    if value is None:
        return ""
    if hasattr(value, "tzinfo"):
        value = timezone.localtime(value)
    return f"{value:%A}, {value:%B} {value.day}"


@register.filter
def clock(value):
    """9:00 AM, with a no-break space so the time never splits across lines."""
    if value is None:
        return ""
    if hasattr(value, "tzinfo") and getattr(value, "tzinfo", None) is not None:
        value = timezone.localtime(value)
    hour = value.hour % 12 or 12
    return mark_safe(f"{hour}:{value.minute:02d}&nbsp;{'AM' if value.hour < 12 else 'PM'}")


@register.filter
def month_name(number):
    """1 → January."""
    try:
        return MONTHS[int(number) - 1]
    except (TypeError, ValueError, IndexError):
        return ""
