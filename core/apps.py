from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self):
        """Put the request reference on every log record from here on."""
        from core.logging import install_record_factory

        install_record_factory()
