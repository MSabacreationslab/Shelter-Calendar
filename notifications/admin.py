from django.contrib import admin

from accounts.admin import ReadOnlyAdmin
from notifications.models import EmailLog, SentReminder


@admin.register(EmailLog)
class EmailLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "template_key", "to", "sent_at", "error")
    list_filter = ("template_key",)
    search_fields = ("to",)


@admin.register(SentReminder)
class SentReminderAdmin(ReadOnlyAdmin):
    list_display = ("kind", "user", "for_date", "sent_at")
    list_filter = ("kind",)
