"""Django settings for the shelter volunteer scheduler.

Everything that differs between machines comes from environment variables
(see .env.example). A local .env file is read for development convenience
unless DJANGO_IGNORE_DOTENV is set.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from config.env import BAD_DATABASE_URL, database_url_from_env, env_bool, env_list, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

if not env_bool("DJANGO_IGNORE_DOTENV", False):
    load_dotenv(BASE_DIR / ".env")

DEBUG = env_bool("DEBUG", False)
# Demo mode turns on the style guide and (from Phase 1) demo data on the free test site.
DEMO_MODE = env_bool("DEMO_MODE", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key-never-used-when-debug-is-off"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [])
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

INSTALLED_APPS = [
    # The backend: only reachable through the app's own sign-in (config/admin.py).
    "config.apps.ShelterAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "core",
    "accounts",
    "training",
    "scheduling",
    "notifications",
    "dashboard",
]

MIDDLEWARE = [
    # First, so every log line and error page carries the request's reference.
    "core.middleware.RequestRefMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.shelter",
            ],
        },
    },
]

DATABASE_URL = database_url_from_env()
try:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=60,
            conn_health_checks=True,
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", False),
        )
    }
except (ValueError, dj_database_url.ParseError, dj_database_url.UnknownSchemeError):
    # Never echo the value: it contains the database password.
    raise ImproperlyConfigured(BAD_DATABASE_URL) from None
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
# PIN rules are enforced by the accounts app, not Django's password validators.
AUTH_PASSWORD_VALIDATORS = []
LOGIN_URL = "accounts:sign_in"
LOGIN_REDIRECT_URL = "home"
# Each visit restarts the sign-in clock (30 days for volunteers, 12 hours for staff).
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
# How many proxies in front of the app append to X-Forwarded-For (0 = use REMOTE_ADDR).
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Render terminates HTTPS and forwards the original scheme in this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
# The host's health checker calls /healthz over plain HTTP from inside its network.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
# HSTS preload only makes sense on our own domain (V2), not a shared hosting subdomain.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
CSRF_FAILURE_VIEW = "core.views.csrf_failure"

EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 20
# Until a mail account is configured, emails are written to the log instead of sent.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST_USER
    else "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

# Starting values for the ShelterSettings row (SPEC Q19); after that the Admin edits them.
SHELTER_NAME = os.environ.get("SHELTER_NAME", "Humane Society of Madison County")
SHELTER_PHONE = os.environ.get("SHELTER_PHONE", "")
SHELTER_EMAIL = os.environ.get("SHELTER_EMAIL", "")

# The public address, for links in emails and printed setup links.
SITE_URL = os.environ.get("SITE_URL") or (
    f"https://{RENDER_EXTERNAL_HOSTNAME}" if RENDER_EXTERNAL_HOSTNAME else "http://localhost:8000"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_ref": {"()": "core.logging.RequestRefFilter"}},
    "formatters": {"plain": {"format": "%(levelname)s %(name)s ref=%(ref)s %(message)s"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_ref"],
            "formatter": "plain",
        }
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
