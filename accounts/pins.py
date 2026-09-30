"""PIN rules (SPEC §4): exactly 6 digits and not easy to guess."""

import re

PIN_LENGTH = 6
COMMON_PINS = {"123321", "111222", "147258", "159753", "102030"}

WRONG_FORMAT = "Please enter exactly 6 numbers."
TOO_EASY = "Please pick a PIN that's harder to guess, like one without a pattern."
LOOKS_LIKE_PHONE = "Please don't use the end of your phone number. Pick a different PIN."


def _is_straight_run(pin: str) -> bool:
    """012345, 456789, 987654 and the like."""
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:], strict=False)}
    return steps in ({1}, {-1})


def _is_repeating_pattern(pin: str) -> bool:
    """121212, 123123, 112233, 111222 and the like."""
    return (
        pin == pin[:2] * 3
        or pin == pin[:3] * 2
        or (pin[0] == pin[1] and pin[2] == pin[3] and pin[4] == pin[5])
        or (len(set(pin[:3])) == 1 and len(set(pin[3:])) == 1)
    )


def pin_problem(pin: str, phone: str = "") -> str | None:
    """Return a plain-language reason the PIN can't be used, or None if it's fine."""
    if not re.fullmatch(rf"\d{{{PIN_LENGTH}}}", pin or ""):
        return WRONG_FORMAT
    if len(set(pin)) == 1 or _is_straight_run(pin) or _is_repeating_pattern(pin):
        return TOO_EASY
    if pin in COMMON_PINS:
        return TOO_EASY
    phone_digits = re.sub(r"\D", "", phone or "")
    if len(phone_digits) >= PIN_LENGTH and pin == phone_digits[-PIN_LENGTH:]:
        return LOOKS_LIKE_PHONE
    return None
