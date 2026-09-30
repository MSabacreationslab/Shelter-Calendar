from django.urls import path

from scheduling import views

app_name = "scheduling"

urlpatterns = [
    path("schedule/", views.week, name="week"),
    path("schedule/add/", views.add_shift, name="add_shift"),
    path("schedule/fill/", views.fill, name="fill"),
    path("schedule/shifts/<int:pk>/", views.shift_detail, name="shift"),
    path("schedule/shifts/<int:pk>/assign/", views.assign, name="assign"),
    path("schedule/shifts/<int:pk>/remove/<int:signup_pk>/", views.remove, name="remove"),
    path(
        "schedule/shifts/<int:pk>/waitlist/<int:entry_pk>/promote/",
        views.promote,
        name="promote",
    ),
    path("schedule/shifts/<int:pk>/waitlist/<int:entry_pk>/remove/", views.unwait, name="unwait"),
    path("schedule/shifts/<int:pk>/edit/", views.edit_shift, name="edit_shift"),
    path("schedule/shifts/<int:pk>/cancel/", views.cancel_shift, name="cancel_shift"),
    path("schedule/templates/", views.templates, name="templates"),
    path("schedule/templates/<int:pk>/", views.template_detail, name="template"),
    path("schedule/templates/<int:pk>/add/", views.add_pattern, name="add_pattern"),
    path("schedule/patterns/<int:pk>/", views.edit_pattern, name="edit_pattern"),
    path("schedule/patterns/<int:pk>/stop/", views.end_pattern, name="end_pattern"),
    path("schedule/closed-days/", views.closed_days, name="closed_days"),
    path(
        "schedule/closed-days/<int:pk>/remove/",
        views.remove_closed_days,
        name="remove_closed_days",
    ),
    path("schedule/holidays/", views.holiday_list, name="holidays"),
    path("schedule/holidays/<int:pk>/toggle/", views.toggle_holiday, name="toggle_holiday"),
    path("schedule/holidays/<int:pk>/remove/", views.remove_holiday, name="remove_holiday"),
    path("orientation/<str:token>/", views.orientation_conflict, name="orientation_conflict"),
]
