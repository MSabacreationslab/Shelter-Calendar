from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("sign-in/", views.sign_in, name="sign_in"),
    path("sign-out/", views.sign_out, name="sign_out"),
    path("welcome/<str:token>/", views.setup_pin, name="setup_pin"),
]
