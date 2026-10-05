"""Print a fresh setup link for someone, for when the email can't reach them."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts import services
from accounts.models import SetupLinkPurpose, Status, User, normalize_login_name


class Command(BaseCommand):
    help = 'Print a new PIN link for an existing person. Usage: setup_link "First Last"'

    def add_arguments(self, parser):
        """The person's sign-in name."""
        parser.add_argument("name", help='Their sign-in name in quotes, e.g. "Cindy Grigsby".')

    @transaction.atomic
    def handle(self, *args, name, **options):
        """Make a one-time link (older unused ones stop working) and print it to pass on."""
        login_name = normalize_login_name(name)
        person = User.objects.filter(login_name__iexact=login_name).first()
        if person is None:
            raise CommandError(f"Nobody signs in as {login_name!r}. Check the spelling.")
        if person.status != Status.ACTIVE:
            raise CommandError(f"{login_name!r} is turned off. Turn them back on first.")
        purpose = (
            SetupLinkPurpose.RESET if person.has_usable_password() else SetupLinkPurpose.INVITE
        )
        token = services.create_setup_link(person, purpose=purpose)
        self.stdout.write(
            f"Give {person.get_full_name()} this link. It works once, within 7 days, and "
            "any earlier link has stopped working:"
        )
        self.stdout.write(services.setup_link_url(token))
