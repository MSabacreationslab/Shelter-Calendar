from django.contrib import admin

from scheduling.models import (
    BlackoutPeriod,
    Holiday,
    Shift,
    ShiftPattern,
    Signup,
    TemplateWeek,
    WaitlistEntry,
)


@admin.register(TemplateWeek)
class TemplateWeekAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(ShiftPattern)
class ShiftPatternAdmin(admin.ModelAdmin):
    list_display = ("title", "weekday", "start_time", "end_time", "capacity", "template_week")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "capacity", "status", "holiday_name")
    list_filter = ("status", "kind")
    date_hierarchy = "starts_at"


@admin.register(Signup)
class SignupAdmin(admin.ModelAdmin):
    list_display = ("volunteer", "shift", "status", "is_late_cancel")
    list_filter = ("status",)


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("volunteer", "shift", "status", "created_at")


@admin.register(BlackoutPeriod)
class BlackoutPeriodAdmin(admin.ModelAdmin):
    list_display = ("reason", "start_date", "end_date")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "source", "hidden")
    list_filter = ("source", "hidden")
