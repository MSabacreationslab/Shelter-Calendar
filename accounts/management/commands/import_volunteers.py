"""Load current volunteers from the shelter's spreadsheet, saved as CSV (SPEC §6, Phase 9)."""

from django.core.management.base import BaseCommand, CommandError

from accounts import importing
from accounts.models import Role, User


class Command(BaseCommand):
    help = (
        "Preview adding volunteers from the shelter's spreadsheet (saved as CSV UTF-8). "
        "Nothing changes unless you add --save."
    )

    def add_arguments(self, parser):
        """The file, and --save to actually add people."""
        parser.add_argument("file", help="The spreadsheet, saved from Excel as CSV UTF-8.")
        parser.add_argument(
            "--save", action="store_true", help="Add the people (without it, only a preview)."
        )

    def handle(self, *args, **options):
        """Show what the file holds, then add everyone at once if --save is given."""
        admin = User.objects.filter(role=Role.ADMIN).order_by("pk").first()
        if admin is None:
            raise CommandError("Create the Admin account first (manage.py create_admin).")
        try:
            result = importing.plan(importing.open_csv(options["file"]))
        except (importing.SpreadsheetError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self._report(result)
        if not options["save"]:
            self.stdout.write("\nThis was a preview. Nothing was added. Add --save to add them.")
            return
        added = importing.save(result, by=admin)
        for person in result.people:
            for warning in person.warnings:
                if warning.startswith("signs in as"):
                    self.stdout.write(f"  Row {person.row}, {person.name}: {warning}")
        self.stdout.write(self.style.SUCCESS(f"\nAdded {len(added)} volunteers."))
        self.stdout.write(
            "No emails were sent. Record each person's training in the app, then send their "
            "welcome link from their page when they're ready."
        )

    def _report(self, result):
        """The preview: counts first, then anything that needs a look."""
        people = result.people
        approval = sum(1 for p in people if not p.active)
        minors = sum(1 for p in people if p.minor)
        self.stdout.write(f"Ready to add: {len(people)} volunteers")
        self.stdout.write(f"  Need approval for every shift (not ACTIVE): {approval}")
        self.stdout.write(f"  Minors: {minors}")
        self.stdout.write(f"  Without an email address: {sum(1 for p in people if not p.email)}")
        self.stdout.write(f"Jobs found: {', '.join(result.jobs) or 'none'}")
        if result.new_jobs:
            self.stdout.write(f"  New on the skills list: {', '.join(result.new_jobs)}")
        if result.ignored_columns:
            self.stdout.write(f"Columns not brought in: {', '.join(result.ignored_columns)}")
        if result.skipped:
            self.stdout.write(self.style.WARNING(f"\nSkipped: {len(result.skipped)}"))
            for row, name, why in result.skipped:
                self.stdout.write(f"  Row {row}, {name}: {why}")
        warned = [p for p in people if p.warnings]
        if warned:
            self.stdout.write(self.style.WARNING(f"\nWorth a look: {len(warned)}"))
            for person in warned:
                for warning in person.warnings:
                    self.stdout.write(f"  Row {person.row}, {person.name}: {warning}")
