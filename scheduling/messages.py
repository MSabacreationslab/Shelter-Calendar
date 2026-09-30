"""Plain-language explanations of booking problems, for volunteers and for staff."""

from core.templatetags.formatting import clock_text, long_date
from scheduling.services import Problem, Result
from training import eligibility


def _when(shift) -> str:
    return f"{long_date(shift.starts_at)} at {clock_text(shift.starts_at)}"


def _names(people) -> str:
    return ", ".join(p.get_full_name() for p in people or [])


def explain(result: Result, *, shift=None, person=None) -> str:
    """One sentence saying what went wrong. With `person`, it's worded for staff."""
    who = person.get_full_name() if person else "You"
    has = f"{who} has" if person else "You have"
    is_ = f"{who} is" if person else "You're"
    problem = result.problem
    if problem == Problem.FULL:
        return "This shift is full."
    if problem == Problem.CANCELLED:
        return "This shift was cancelled."
    if problem == Problem.STARTED:
        return "This shift has already started."
    if problem == Problem.OVERLAP:
        if result.other_shift:
            other = result.other_shift
            return f"{has} another shift at the same time: {other.title} on {_when(other)}."
        return f"{has} another shift at the same time."
    if problem == Problem.WAITLIST_FULL:
        return "The waitlist for this shift is full."
    if problem == Problem.HAS_SPACE:
        return "There's still a spot, so you can sign up instead."
    if problem == Problem.NOT_WAITING:
        return f"{is_} not on the waitlist any more."
    if problem == Problem.CAPACITY_BELOW_SIGNUPS:
        return (
            f"{len(result.people)} people are signed up ({_names(result.people)}), "
            "so the shift can't hold fewer than that."
        )
    if problem == Problem.TIME_CLASH:
        return f"The new time would overlap other shifts for: {_names(result.people)}."
    if problem == Problem.MISSING_TRAINING:
        return f"These people don't have that training yet: {_names(result.people)}."
    if problem == Problem.NOT_ELIGIBLE:
        return _ineligible(result.reason, shift, who, person is not None)
    return "Something went wrong. Please try again."


def _ineligible(reason, shift, who, for_staff) -> str:
    needs = f"{who} needs" if for_staff else "You need"
    if reason == eligibility.NEEDS_TRAINING and shift and shift.required_training:
        return f"{needs} {shift.required_training.name} training before signing up for this shift."
    if reason == eligibility.NEEDS_ORIENTATION:
        if for_staff:
            return (
                f"{who} can't take shifts yet. Finish their orientation or allow "
                "no-training shifts first."
            )
        return "You can sign up for shifts once you've done your orientation."
    if reason == eligibility.SESSION_NOT_NEEDED:
        return (
            "This training session is for people who still need it. "
            "Ask the volunteer team if you'd like to join."
        )
    if reason == eligibility.TURNED_OFF:
        return f"{who}'s account is turned off." if for_staff else "Your account is turned off."
    return "This shift isn't available."
