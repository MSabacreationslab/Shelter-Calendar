import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware

from tests.factories import AdminFactory, StaffFactory, UserFactory


@pytest.fixture(autouse=True)
def _plain_test_settings(settings):
    """Serve static files unhashed, skip the HTTPS redirect, and hash PINs quickly."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.SECURE_SSL_REDIRECT = False
    # The real hasher is deliberately slow; tests hash hundreds of PINs.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def volunteer(db):
    """An active volunteer whose PIN is TEST_PIN."""
    return UserFactory()


@pytest.fixture
def staff(db):
    """An active staff member whose PIN is TEST_PIN."""
    return StaffFactory()


@pytest.fixture
def admin_person(db):
    """The Admin, whose PIN is TEST_PIN."""
    return AdminFactory()


@pytest.fixture
def session_request(rf):
    """Build a POST request with a session, for calling sign-in services directly."""

    def build(ip="203.0.113.5"):
        request = rf.post("/sign-in/", REMOTE_ADDR=ip)
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = AnonymousUser()
        return request

    return build
