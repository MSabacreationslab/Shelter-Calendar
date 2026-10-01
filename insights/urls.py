from django.urls import path

from insights import views

app_name = "insights"

urlpatterns = [
    path("admin/usage/", views.usage, name="usage"),
    path("admin/hotspots/", views.hotspots, name="hotspots"),
    path("admin/problems/", views.problem_list, name="problems"),
    path("admin/problems/test/", views.test_alert, name="test_alert"),
]
