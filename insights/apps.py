from django.apps import AppConfig


class InsightsConfig(AppConfig):
    """Usage, hotspots and problem alerts for the Admin."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "insights"

    def ready(self):
        """Keep each request's exception so the error page can report its traceback."""
        from django.core.signals import got_request_exception

        from insights.problems import remember_exception

        got_request_exception.connect(remember_exception, dispatch_uid="insights_exception")
