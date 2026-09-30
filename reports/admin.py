from django.contrib import admin

from accounts.admin import ReadOnlyAdmin
from reports.models import SentReport


@admin.register(SentReport)
class SentReportAdmin(ReadOnlyAdmin):
    list_display = ("kind", "period_start", "sent_at", "recipients")
