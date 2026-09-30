from django.contrib import admin

from accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("login_name", "email", "is_staff", "is_active", "date_joined")
    search_fields = ("login_name", "first_name", "last_name", "email")
    ordering = ("login_name",)
    # PINs are never shown or edited here; people set their own from a setup link.
    exclude = ("password",)
