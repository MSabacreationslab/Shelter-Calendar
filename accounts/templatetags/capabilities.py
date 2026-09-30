"""Template checks for capabilities: {% if request.user|can:"view_dashboard" %}."""

from django import template

from accounts.permissions import has_capability

register = template.Library()


@register.filter
def can(user, capability):
    """True if the person may do this; templates never check role names."""
    return has_capability(user, capability)
