"""Helpers shared by management commands."""

from datetime import date

from django.core.management import CommandError


def parse_date_option(value: str | None) -> date | None:
    """The --date option: None when absent, a clear error when it isn't YYYY-MM-DD."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError("Use a date like 2026-10-04.") from exc
