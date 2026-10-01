from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("admin/", views.admin_hub, name="admin"),
    path("changes/", views.change_log, name="change_log"),
    path("settings/", views.shelter_settings, name="settings"),
    path("staff/", views.staff_list, name="staff"),
    path("staff/add/", views.add_staff, name="add_staff"),
]
