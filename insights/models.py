"""What the Admin's usage, hotspot and problem pages are built from.

Page visits store the page's name (like "shifts:shift"), never its full address, so
no ids or personal details end up here. Both tables are pruned (prune_usage).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class PageView(models.Model):
    """One page opened (or form sent) by someone."""

    at = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    role = models.CharField(max_length=20, blank=True, help_text="Blank when signed out.")
    route = models.CharField(max_length=100, help_text='The page\'s name, like "shifts:shift".')
    method = models.CharField(max_length=8)
    status = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    device = models.CharField(max_length=10)
    came_from = models.CharField(max_length=100, blank=True, help_text="The previous page's name.")
    # A form that came back with something to fix.
    form_problem = models.BooleanField(default=False)

    class Meta:
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["at"]),
            models.Index(fields=["route", "at"]),
            models.Index(fields=["user", "at"]),
        ]

    def __str__(self):
        return f"{self.route} at {self.at:%Y-%m-%d %H:%M}"


class Problem(models.Model):
    """One error, with what the Admin needs to find and fix it."""

    at = models.DateTimeField(default=timezone.now)
    code = models.CharField(max_length=10)
    status = models.PositiveSmallIntegerField(null=True, blank=True)
    ref = models.CharField(max_length=10, blank=True)
    route = models.CharField(max_length=100, blank=True)
    path = models.CharField(max_length=200, blank=True)
    method = models.CharField(max_length=8, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    role = models.CharField(max_length=20, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    details = models.TextField(blank=True)
    emailed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["code", "route", "at"]), models.Index(fields=["at"])]

    def __str__(self):
        return f"{self.code} {self.ref} at {self.at:%Y-%m-%d %H:%M}"
