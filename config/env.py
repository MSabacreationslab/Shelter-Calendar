"""Small helpers for reading settings from environment variables and a local .env file."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

TRUE_VALUES = {"1", "true", "yes", "on"}


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from path into os.environ without overriding real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def env_bool(name: str, default: bool) -> bool:
    """Read a yes/no environment variable."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in TRUE_VALUES


def env_list(name: str, default: list[str]) -> list[str]:
    """Read a comma-separated environment variable into a list."""
    value = os.environ.get(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default)


BAD_DATABASE_URL = (
    "DATABASE_URL isn't a database address the app can read. It should be one line like "
    "postgresql://USER:PASSWORD@HOST:5432/NAME, with no quotes and nothing before it. "
    "Remove any [ ] around the password, and write special characters in the password as "
    "codes: # as %23, @ as %40, / as %2F, : as %3A, % as %25, ? as %3F, & as %26 "
    "(see docs/setup.md)."
)


def database_url_from_env() -> str:
    """DATABASE_URL, forgiving common pasting slips: quotes, spaces, a "DATABASE_URL=" prefix."""
    value = os.environ.get("DATABASE_URL", "").strip()
    if value.startswith("DATABASE_URL="):
        value = value.split("=", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    if not value:
        raise ImproperlyConfigured("DATABASE_URL must be set (see .env.example).")
    if not value.startswith(("postgres://", "postgresql://")):
        raise ImproperlyConfigured(BAD_DATABASE_URL)
    return value
