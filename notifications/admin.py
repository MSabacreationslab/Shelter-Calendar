from django.contrib import admin

from accounts.admin import ReadOnlyAdmin
from notifications.models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "template_key", "to", "sent_at", "error")
    list_filter = ("template_key",)
    search_fields = ("to",)
