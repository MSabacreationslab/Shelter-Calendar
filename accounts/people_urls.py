from django.urls import path

from accounts import people_views as views

app_name = "people"

urlpatterns = [
    path("volunteers/", views.volunteer_list, name="list"),
    path("volunteers/add/", views.add_volunteer, name="add"),
    path("volunteers/<int:pk>/", views.person_detail, name="detail"),
    path("volunteers/<int:pk>/edit/", views.edit_person, name="edit"),
    path("volunteers/<int:pk>/new-link/", views.send_link, name="send_link"),
    path("volunteers/<int:pk>/turn-off/", views.deactivate, name="deactivate"),
    path("volunteers/<int:pk>/turn-on/", views.reactivate, name="reactivate"),
    path("volunteers/<int:pk>/job-title/", views.job_title, name="job_title"),
    path("volunteers/<int:pk>/view-as/", views.view_as, name="view_as"),
    path("profile/", views.my_profile, name="profile"),
    path("skills/", views.skills, name="skills"),
    path("skills/<int:pk>/", views.edit_skill, name="edit_skill"),
    path("skills/<int:pk>/toggle/", views.toggle_skill, name="toggle_skill"),
]
