"""Create the Admin account (Mike) and print a link for choosing a PIN."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts import services
from accounts.models import Role, SetupLinkPurpose, User, normalize_login_name


class Command(BaseCommand):
    help = 'Create the Admin and print a setup link. Usage: create_admin "First Last" email'

    def add_arguments(self, parser):
        """Name and email, plus --new-link to reissue a link for an existing Admin."""
        parser.add_argument("name", help='Full name in quotes, e.g. "Mike Saba".')
        parser.add_argument("email", nargs="?", default="")
        parser.add_argument(
            "--new-link", action="store_true", help="Send an existing Admin a fresh link."
        )

    @transaction.atomic
    def handle(self, *args, name, email, new_link, **options):
        """Admins can only be made here, so nobody can promote themselves in the app."""
        login_name = normalize_login_name(name)
        existing = User.objects.filter(login_name__iexact=login_name).first()
        if new_link:
            if existing is None or existing.role != Role.ADMIN:
                raise CommandError(f"No Admin named {login_name!r}.")
            token = services.create_setup_link(existing, purpose=SetupLinkPurpose.RESET)
        else:
            if existing is not None:
                raise CommandError(f"{login_name!r} already exists. Use --new-link for a link.")
            if not email:
                raise CommandError("An email address is required.")
            first, _, last = login_name.partition(" ")
            user = services.create_person(
                first_name=first, last_name=last, email=email, role=Role.ADMIN
            )
            token = services.create_setup_link(user, purpose=SetupLinkPurpose.INVITE)
        self.stdout.write("Open this link within 7 days to choose your PIN:")
        self.stdout.write(services.setup_link_url(token))
