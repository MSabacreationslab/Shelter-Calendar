import pytest


@pytest.fixture(autouse=True)
def _plain_test_settings(settings):
    """Serve static files unhashed and skip the HTTPS redirect, so pages render in tests."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.SECURE_SSL_REDIRECT = False
