from django.contrib import admin

from accounts.admin import ReadOnlyAdmin
from core.models import AuditEvent, ShelterSettings


@admin.register(ShelterSettings)
class ShelterSettingsAdmin(admin.ModelAdmin):
    list_display = ("shelter_name", "shelter_phone", "self_cancel_hours", "urgent_threshold_hours")

    def has_add_permission(self, request):
        """There is only ever one settings row."""
        return not ShelterSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """The settings row can't be removed."""
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "action", "actor", "target_user", "target_repr")
    list_filter = ("action",)
    search_fields = ("target_repr",)
