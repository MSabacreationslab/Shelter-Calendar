"""Create the local database named in DATABASE_URL (a one-time setup step)."""

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from psycopg import sql


class Command(BaseCommand):
    help = "Create the database named in DATABASE_URL if it doesn't exist yet."

    def handle(self, *args, **options):
        """Connect to the server's built-in 'postgres' database and create ours."""
        db = settings.DATABASES["default"]
        name = db["NAME"]
        params = {
            "host": db.get("HOST") or "localhost",
            "port": db.get("PORT") or 5432,
            "user": db.get("USER"),
            "password": db.get("PASSWORD"),
            "dbname": "postgres",
        }
        try:
            with psycopg.connect(**params, autocommit=True) as conn:
                exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
                if exists.fetchone():
                    self.stdout.write(f"Database '{name}' already exists.")
                    return
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        except psycopg.OperationalError as exc:
            raise CommandError(f"Couldn't connect to Postgres: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Created database '{name}'."))
