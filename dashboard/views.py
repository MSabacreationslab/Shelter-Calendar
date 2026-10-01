"""The staff dashboard, the change log, staff management and the Admin's settings."""

from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts import people
from accounts.models import Role, User
from accounts.people_forms import StaffForm
from accounts.permissions import has_capability, requires
from core import audit
from core.forms import post_data
from core.models import AuditEvent, ShelterSettings
from dashboard import queries
from dashboard.forms import ChangeLogFilterForm, SettingsForm

CHANGES_PER_PAGE = 50
SETTINGS_FIELDS = [
    "shelter_name",
    "shelter_phone",
    "shelter_email",
    "self_cancel_hours",
    "urgent_threshold_hours",
    "notify_emails",
]


@requires("view_dashboard")
def dashboard(request):
    """Today at a glance, then everything that needs someone's attention."""
    short_count, short_list = queries.short_shifts()
    cancellations = queries.cancellations()
    approvals_count, approvals = queries.waiting_approvals()
    context = {
        "today": queries.today(),
        "today_date": timezone.localdate(),
        "urgent": [s for s in cancellations if s.was_urgent],
        "routine": [s for s in cancellations if not s.was_urgent],
        "approvals": approvals,
        "approvals_count": approvals_count,
        "short_count": short_count,
        "short_list": short_list,
        "waitlists": queries.waitlists_with_space(),
        "conflicts": queries.orientation_conflicts(),
        "expired": queries.expired_links(),
        "locked": queries.locked_out(),
        "settings": ShelterSettings.load(),
        "can": {
            cap: has_capability(request.user, cap)
            for cap in (
                "manage_shifts",
                "add_volunteers",
                "record_training",
                "view_change_log",
                "manage_staff",
                "edit_settings",
                "reset_volunteer_pin",
            )
        },
    }
    sections = ("urgent", "approvals", "short_list", "waitlists", "conflicts", "expired", "locked")
    context["all_clear"] = not any(context[k] for k in sections)
    return render(request, "dashboard/home.html", context)


@requires("view_change_log")
def change_log(request):
    """Every change, newest first. Filters go in the web address as ids and dates only."""
    form = ChangeLogFilterForm(request.GET or None)
    events = AuditEvent.objects.select_related("actor", "target_user")
    if form.is_valid():
        data = form.cleaned_data
        if data["person"]:
            events = events.filter(target_user=data["person"])
        if data["start"]:
            events = events.filter(created_at__date__gte=data["start"])
        if data["end"]:
            events = events.filter(created_at__date__lte=data["end"])
    page = Paginator(events, CHANGES_PER_PAGE).get_page(request.GET.get("page"))
    for event in page:
        event.description = audit.describe(event)
    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "dashboard/change_log.html",
        {"form": form, "page": page, "query": query.urlencode()},
    )


@requires("edit_settings")
def shelter_settings(request):
    """The Admin's settings, including the 24h/48h urgent threshold for the pilot trial."""
    row = ShelterSettings.load()
    form = SettingsForm(post_data(request), initial={f: getattr(row, f) for f in SETTINGS_FIELDS})
    if request.method == "POST" and form.is_valid():
        changed = {
            f: {"from": getattr(row, f), "to": form.cleaned_data[f]}
            for f in SETTINGS_FIELDS
            if getattr(row, f) != form.cleaned_data[f]
        }
        if changed:
            with transaction.atomic():
                for field, values in changed.items():
                    setattr(row, field, values["to"])
                row.save()
                audit.record("settings.changed", actor=request.user, changes=changed)
        messages.success(request, "Settings saved." if changed else "Nothing needed changing.")
        return redirect("dashboard:settings")
    return render(request, "dashboard/settings.html", {"form": form})


# The Admin page: one heading per area, each link shown only to people who can use it.
# (capability, url name, label)
ADMIN_SECTIONS = [
    (
        "Shift approvals",
        "People waiting for your OK to join a shift.",
        [("approve_signups", "scheduling:approvals", "Shift approvals")],
    ),
    (
        "Schedule",
        "Shifts, repeating weeks, closed days and holidays.",
        [
            ("view_full_schedule", "scheduling:week", "This week's schedule"),
            ("manage_shifts", "scheduling:add_shift", "Add a shift"),
            ("manage_shifts", "scheduling:templates", "Template weeks"),
            ("manage_shifts", "scheduling:fill", "Fill the schedule"),
            ("manage_shifts", "scheduling:closed_days", "Closed days"),
            ("manage_shifts", "scheduling:holidays", "Holidays"),
        ],
    ),
    (
        "Volunteers",
        "Everyone's details, adding new volunteers, and the skills list.",
        [
            ("view_contacts", "people:list", "All volunteers"),
            ("add_volunteers", "people:add", "Add a volunteer"),
            ("edit_volunteers", "people:skills", "Skills list"),
        ],
    ),
    (
        "Training",
        "Who has done which training, and recording sessions.",
        [
            ("record_training", "training:overview", "Training"),
            ("record_training", "training:add_record", "Record training"),
        ],
    ),
    (
        "Reports and history",
        "Numbers, downloads, and every change anyone has made.",
        [
            ("view_reports", "reports:report", "Reports and downloads"),
            ("view_change_log", "dashboard:change_log", "Change log"),
        ],
    ),
    (
        "Staff",
        "The leads' accounts and job titles.",
        [
            ("manage_staff", "dashboard:staff", "Staff list"),
            ("manage_staff", "dashboard:add_staff", "Add a staff member"),
        ],
    ),
    (
        "Admin only",
        "Only the Admin sees this section.",
        [
            ("edit_settings", "dashboard:settings", "Shelter settings"),
            ("view_usage", "insights:usage", "Usage"),
            ("view_usage", "insights:hotspots", "Hotspots"),
            ("view_usage", "insights:problems", "Problems"),
            ("edit_settings", "admin:index", "Backend"),
        ],
    ),
]


@requires("view_dashboard")
def admin_hub(request):
    """Every staff area in one place, so the menu stays short."""
    from insights.models import Problem
    from scheduling.services import waiting_requests

    waiting = waiting_requests().count()
    recent = Problem.objects.filter(at__gte=timezone.now() - timedelta(days=7)).count()
    notes = {
        "scheduling:approvals": f"{waiting} waiting" if waiting else "",
        "insights:problems": f"{recent} this week" if recent else "",
    }
    sections = []
    for title, about, links in ADMIN_SECTIONS:
        allowed = [
            {"url": reverse(name), "label": label, "note": notes.get(name, "")}
            for capability, name, label in links
            if has_capability(request.user, capability)
        ]
        if allowed:
            sections.append({"title": title, "about": about, "links": allowed})
    return render(request, "dashboard/admin.html", {"sections": sections})


@requires("manage_staff")
def staff_list(request):
    """The shelter's staff (the Admin isn't listed)."""
    staff = User.objects.filter(role=Role.STAFF).order_by("status", "first_name", "last_name")
    return render(request, "dashboard/staff.html", {"staff": staff})


@requires("manage_staff")
def add_staff(request):
    """Add a staff member; they get a welcome email to choose their PIN."""
    form = StaffForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        person = people.add_staff(form.cleaned_data, added_by=request.user)
        messages.success(
            request,
            f"{person.get_full_name()} is added. We've emailed them a link to choose a PIN.",
        )
        return redirect("people:detail", pk=person.pk)
    return render(request, "dashboard/staff_add.html", {"form": form})
