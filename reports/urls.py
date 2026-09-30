from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("reports/", views.report, name="report"),
    path("reports/<str:table>.csv", views.download, name="download"),
]
