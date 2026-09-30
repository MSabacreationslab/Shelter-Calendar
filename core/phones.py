"""US phone numbers: stored as 10 digits, shown as (740) 555-0100."""

import re


def normalize_phone(value: str) -> str:
    """Digits only, however it was typed. Raises ValueError if it isn't a 10-digit number."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Please enter a 10-digit phone number, like (740) 555-0100.")
    return digits


def format_phone(digits: str) -> str:
    """(740) 555-0100 for 10 digits; anything else is shown as stored."""
    if re.fullmatch(r"\d{10}", digits or ""):
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits or ""
