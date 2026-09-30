"""Small helpers for reading settings from environment variables and a local .env file."""

import os
from pathlib import Path

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
