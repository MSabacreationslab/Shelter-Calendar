"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("", core_views.home, name="home"),
    path("healthz", core_views.healthz, name="healthz"),
    path("styleguide/", core_views.styleguide, name="styleguide"),
    path("", include("accounts.urls")),
    path("", include("accounts.people_urls")),
    path("", include("scheduling.urls")),
    path("", include("scheduling.volunteer_urls")),
    path("", include("training.urls")),
    path("", include("dashboard.urls")),
    path("", include("reports.urls")),
    path("", include("insights.urls")),
    # Emergency backend for the Admin only; never part of a staff workflow.
    path("django-admin/", admin.site.urls),
]

handler400 = "core.views.bad_request"
handler403 = "core.views.permission_denied"
handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
