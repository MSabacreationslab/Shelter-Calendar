"""Helpers shared by management commands."""

import traceback
from datetime import date

from django.core.management import BaseCommand, CommandError


def parse_date_option(value: str | None) -> date | None:
    """The --date option: None when absent, a clear error when it isn't YYYY-MM-DD."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError("Use a date like 2026-10-04.") from exc


class ReportedCommand(BaseCommand):
    """A scheduled command: if it crashes, the Admin is emailed (SC-106) before it exits."""

    def execute(self, *args, **options):
        """Run the command; report anything unexpected, then let it fail as before."""
        try:
            return super().execute(*args, **options)
        except CommandError:
            raise  # a mistake in how it was run, already explained on screen
        except Exception as exc:
            from core import errors
            from insights import problems

            name = type(self).__module__.rsplit(".", 1)[-1]
            problems.report(
                errors.TASK_FAILED,
                route=f"task: {name}",
                summary=f"{type(exc).__name__}: {exc}",
                details=traceback.format_exc(),
            )
            raise
