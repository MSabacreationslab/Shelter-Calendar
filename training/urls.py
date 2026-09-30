from django.urls import path

from training import views

app_name = "training"

urlpatterns = [
    path("training/", views.overview, name="overview"),
    path("training/add/", views.add_record, name="add_record"),
    path("training/types/<int:pk>/", views.rename_type, name="rename_type"),
    path("training/types/<int:pk>/toggle/", views.toggle_type, name="toggle_type"),
    path("training/sessions/<int:pk>/", views.session, name="session"),
    path("training/records/<int:pk>/void/", views.void, name="void"),
    path("training/people/<int:pk>/needs/", views.add_need, name="add_need"),
    path("training/needs/<int:pk>/remove/", views.remove_need, name="remove_need"),
    path("training/people/<int:pk>/no-training/", views.no_training, name="no_training"),
]
