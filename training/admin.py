from django.contrib import admin

from training.models import TrainingNeed, TrainingRecord, TrainingType


@admin.register(TrainingType)
class TrainingTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_orientation", "active")


@admin.register(TrainingNeed)
class TrainingNeedAdmin(admin.ModelAdmin):
    list_display = ("volunteer", "training_type", "created_at", "resolved_at")


@admin.register(TrainingRecord)
class TrainingRecordAdmin(admin.ModelAdmin):
    list_display = ("volunteer", "training_type", "completed_on", "signed_off_by", "voided_at")
    list_filter = ("training_type",)
