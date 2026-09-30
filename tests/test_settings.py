"""Settings are checked in a fresh process so each case sees only the env it sets."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CLEARED = {
    "DEBUG",
    "SECRET_KEY",
    "DATABASE_URL",
    "ALLOWED_HOSTS",
    "DEMO_MODE",
    "DATABASE_SSL_REQUIRE",
    "RENDER_EXTERNAL_HOSTNAME",
}


def _env(**overrides):
    """A clean environment that ignores the developer's .env file."""
    env = {k: v for k, v in os.environ.items() if k not in CLEARED}
    env.update(
        DJANGO_IGNORE_DOTENV="1",
        DJANGO_SETTINGS_MODULE="config.settings",
        DATABASE_URL="postgres://user:pass@localhost:5432/unused",
    )
    env.update(overrides)
    return env


def _run(args, env):
    """Run a Python command in the project directory."""
    return subprocess.run(
        [sys.executable, *args], cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=120
    )


def test_debug_is_off_by_default():
    result = _run(["-c", "import config.settings as s; print(s.DEBUG)"], _env(SECRET_KEY="x" * 60))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_secret_key_is_required_when_debug_is_off():
    result = _run(["-c", "import config.settings"], _env())
    assert result.returncode != 0
    assert "SECRET_KEY must be set" in result.stderr


def test_render_hostname_is_allowed_and_trusted():
    code = "import config.settings as s; print(s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS)"
    env = _env(SECRET_KEY="x" * 60, RENDER_EXTERNAL_HOSTNAME="shelter.onrender.com")
    result = _run(["-c", code], env)
    assert "shelter.onrender.com" in result.stdout
    assert "https://shelter.onrender.com" in result.stdout


def test_deploy_check_passes_with_production_settings():
    env = _env(SECRET_KEY=secrets.token_urlsafe(50), ALLOWED_HOSTS="shelter.example.org")
    result = _run(["manage.py", "check", "--deploy", "--fail-level", "WARNING"], env)
    assert result.returncode == 0, result.stdout + result.stderr
