from django.contrib import admin

from accounts.models import LoginAttempt, SetupLink, Skill, User, VolunteerProfile


class VolunteerProfileInline(admin.StackedInline):
    model = VolunteerProfile
    fk_name = "user"
    can_delete = False
    filter_horizontal = ("skills",)
    readonly_fields = ("added_by",)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("login_name", "role", "job_title", "status", "email", "last_login")
    list_filter = ("role", "status")
    search_fields = ("login_name", "first_name", "last_name", "email")
    ordering = ("login_name",)
    inlines = [VolunteerProfileInline]
    # PINs are never shown or set here; people choose their own from a setup link.
    exclude = ("password", "groups", "user_permissions")
    readonly_fields = ("last_login", "date_joined", "locked_until")


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "active")


class ReadOnlyAdmin(admin.ModelAdmin):
    """Records the app writes itself; the backend can look but not change them."""

    def has_add_permission(self, request):
        """Never added by hand."""
        return False

    def has_change_permission(self, request, obj=None):
        """Never edited by hand."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Never deleted by hand."""
        return False


@admin.register(SetupLink)
class SetupLinkAdmin(ReadOnlyAdmin):
    list_display = ("user", "purpose", "created_at", "expires_at", "used_at", "voided_at")
    exclude = ("token_hash",)


@admin.register(LoginAttempt)
class LoginAttemptAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "name_entered", "user", "ip", "succeeded")
    list_filter = ("succeeded",)
    search_fields = ("name_entered", "ip")
