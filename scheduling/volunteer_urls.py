from django.urls import path

from scheduling import volunteer_views as views

app_name = "shifts"

urlpatterns = [
    path("my-shifts/", views.my_shifts, name="home"),
    path("my-shifts/<str:day>/", views.day, name="day"),
    path("shifts/", views.find, name="find"),
    path("shifts/<int:pk>/", views.shift_page, name="shift"),
    path("shifts/<int:pk>/sign-up/", views.sign_up, name="sign_up"),
    path("shifts/<int:pk>/signed-up/", views.signed_up, name="signed_up"),
    path("shifts/<int:pk>/ask/", views.ask, name="ask"),
    path("shifts/<int:pk>/take-back/", views.take_back, name="take_back"),
    path("shifts/<int:pk>/calendar.ics", views.calendar_file, name="calendar_file"),
    path("shifts/<int:pk>/cancel/", views.cancel, name="cancel"),
    path("shifts/<int:pk>/waitlist/", views.join_waitlist, name="join_waitlist"),
    path("shifts/<int:pk>/leave-waitlist/", views.leave_waitlist, name="leave_waitlist"),
]
