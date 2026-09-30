from django.contrib.admin.apps import AdminConfig


class ShelterAdminConfig(AdminConfig):
    default_site = "config.admin.ShelterAdminSite"
