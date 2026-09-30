"""The Django admin backend, for the Admin only."""

from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse


class ShelterAdminSite(admin.AdminSite):
    site_header = "Shelter scheduler backend"
    site_title = "Backend"
    index_title = "Backend (Admin only)"

    def has_permission(self, request):
        """Only the Admin, and only while their account is active."""
        user = request.user
        return user.is_active and user.is_staff and getattr(user, "is_admin", False)

    def login(self, request, extra_context=None):
        """Send backend sign-ins through the app's sign-in, which has the lockout rules."""
        target = request.GET.get(REDIRECT_FIELD_NAME) or reverse("admin:index")
        return redirect_to_login(target, reverse("accounts:sign_in"))
