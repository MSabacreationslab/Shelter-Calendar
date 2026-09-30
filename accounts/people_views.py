"""Staff screens: the volunteer list, adding and editing volunteers, setup links, skills."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import people
from accounts.models import Role, Skill, Status, User
from accounts.people_forms import (
    AddVolunteerForm,
    DirectoryFilterForm,
    JobTitleForm,
    OwnContactForm,
    SkillForm,
    VolunteerDetailsForm,
    details_initial,
)
from accounts.permissions import has_capability, requires
from core import audit
from core.forms import post_data
from core.models import AuditEvent
from scheduling.models import Signup, SignupStatus
from scheduling.volunteer_views import home_context
from training.forms import NeedForm
from training.models import TrainingNeed, TrainingRecord

SETUP_TEMPLATES = ["welcome", "new_pin"]


def _person_or_404(pk):
    """Volunteers and staff; the Admin never appears in staff screens."""
    return get_object_or_404(
        User.objects.select_related("profile"), pk=pk, role__in=[Role.VOLUNTEER, Role.STAFF]
    )


@requires("view_contacts")
def volunteer_list(request):
    """Everyone, A to Z, narrowed by who, status and training. The name box filters in the
    browser, so names never end up in web addresses or logs."""
    filters = DirectoryFilterForm(request.GET or None)
    data = filters.cleaned_data if filters.is_valid() else {}
    who = data.get("who") or "volunteers"
    listed = User.objects.filter(role__in=[Role.VOLUNTEER, Role.STAFF]).select_related("profile")
    if who == "volunteers":
        listed = listed.filter(role=Role.VOLUNTEER)
    elif who == "staff":
        listed = listed.filter(role=Role.STAFF)
    if (data.get("status") or "active") == "active":
        listed = listed.filter(status=Status.ACTIVE)
    if data.get("done"):
        listed = listed.filter(
            training_records__training_type=data["done"], training_records__voided_at__isnull=True
        )
    if data.get("needs"):
        listed = listed.filter(
            training_needs__training_type=data["needs"], training_needs__resolved_at__isnull=True
        )
    return render(
        request,
        "people/list.html",
        {"volunteers": listed.distinct().order_by("first_name", "last_name"), "filters": filters},
    )


@requires("add_volunteers")
def add_volunteer(request):
    """One page, one Save: details, sign-in name, training, then the welcome email."""
    form = AddVolunteerForm(post_data(request))
    duplicates = []
    if request.method == "POST" and form.is_valid():
        duplicates = form.possible_duplicates()
        if not duplicates or request.POST.get("add_anyway"):
            added = people.add_volunteer(form.cleaned_data, added_by=request.user)
            person = added.person
            messages.success(
                request,
                f"{person.get_full_name()} is added. We've emailed them a link to choose a PIN.",
            )
            if added.orientation_booked is False:
                messages.warning(
                    request,
                    "That orientation session filled up, so they aren't booked on one yet. "
                    "Add them from the session's page in the schedule.",
                )
            return redirect("people:detail", pk=person.pk)
    return render(request, "people/add.html", {"form": form, "duplicates": duplicates})


@requires("view_contacts")
def person_detail(request, pk):
    """Everything about one person, plus the latest setup email and whether it went out."""
    person = _person_or_404(pk)
    now = timezone.now()
    context = {
        "person": person,
        "profile": person.profile,
        "has_pin": person.has_usable_password(),
        "last_setup_email": person.email_logs.filter(template_key__in=SETUP_TEMPLATES).first(),
        "open_needs": TrainingNeed.objects.filter(volunteer=person, resolved_at__isnull=True)
        .select_related("training_type")
        .order_by("training_type__name"),
        "records": TrainingRecord.objects.filter(volunteer=person, voided_at__isnull=True)
        .select_related("training_type")
        .order_by("training_type__name"),
        "need_form": NeedForm(person=person),
        "can_record": has_capability(request.user, "record_training"),
        "can_edit": has_capability(request.user, "edit_volunteers"),
        "can_send_link": people.can_send_link(request.user, person),
        "can_manage": people.can_manage(request.user, person),
        "can_view_as": person.role == Role.VOLUNTEER
        and has_capability(request.user, "view_as_volunteer"),
        "job_title_form": JobTitleForm(initial={"job_title": person.job_title})
        if person.role == Role.STAFF and has_capability(request.user, "manage_staff")
        else None,
        "upcoming": Signup.objects.filter(
            volunteer=person, status=SignupStatus.CONFIRMED, shift__starts_at__gt=now
        )
        .select_related("shift")
        .order_by("shift__starts_at")[:10],
        "history": Signup.objects.filter(volunteer=person, shift__starts_at__lte=now)
        .select_related("shift")
        .order_by("-shift__starts_at")[:10],
        "changes": [
            (event, audit.describe(event))
            for event in AuditEvent.objects.filter(target_user=person).select_related("actor")[:15]
        ]
        if has_capability(request.user, "view_change_log")
        else [],
    }
    return render(request, "people/detail.html", context)


@requires("edit_volunteers")
def edit_person(request, pk):
    """Change someone's details. Only the fields that changed go in the change log."""
    person = _person_or_404(pk)
    form = VolunteerDetailsForm(post_data(request), initial=details_initial(person), person=person)
    if request.method == "POST" and form.is_valid():
        changed = people.update_volunteer(person, form.cleaned_data, by=request.user)
        messages.success(request, "Changes saved." if changed else "Nothing needed changing.")
        return redirect("people:detail", pk=person.pk)
    return render(request, "people/edit.html", {"form": form, "person": person})


@requires("reset_volunteer_pin")
@require_POST
def send_link(request, pk):
    """Email a fresh link: a welcome if they never chose a PIN, otherwise a new-PIN link."""
    person = _person_or_404(pk)
    if not people.can_send_link(request.user, person):
        raise PermissionDenied
    people.send_new_setup_link(person, by=request.user)
    messages.success(request, f"We've emailed {person.get_short_name()} a new link.")
    return redirect("people:detail", pk=person.pk)


@requires("edit_volunteers")
def skills(request):
    """The skills list: add new ones, rename, or take them off the list."""
    form = SkillForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        people.add_skill(form.cleaned_data["name"], by=request.user)
        messages.success(request, f"“{form.cleaned_data['name']}” is on the list.")
        return redirect("people:skills")
    return render(
        request, "people/skills.html", {"form": form, "skills": Skill.objects.order_by("name")}
    )


@requires("edit_volunteers")
def edit_skill(request, pk):
    """Rename one skill."""
    skill = get_object_or_404(Skill, pk=pk)
    form = SkillForm(post_data(request), initial={"name": skill.name}, skill=skill)
    if request.method == "POST" and form.is_valid():
        people.rename_skill(skill, form.cleaned_data["name"], by=request.user)
        messages.success(request, "Skill renamed.")
        return redirect("people:skills")
    return render(request, "people/skill_edit.html", {"form": form, "skill": skill})


@requires("edit_volunteers")
@require_POST
def toggle_skill(request, pk):
    """Take a skill off the list or put it back. People who have it keep it."""
    skill = get_object_or_404(Skill, pk=pk)
    people.set_skill_active(skill, not skill.active, by=request.user)
    return redirect("people:skills")


@requires("edit_own_contact")
def my_profile(request):
    """Your details. You can change your phone and emergency contact; call for anything else."""
    person = request.user
    profile = person.profile
    initial = {
        "phone": person.phone,
        "emergency_contact_name": profile.emergency_contact_name,
        "emergency_contact_phone": profile.emergency_contact_phone,
        "emergency_contact_relationship": profile.emergency_contact_relationship,
    }
    form = OwnContactForm(post_data(request), initial=initial)
    if request.method == "POST" and form.is_valid():
        changed = people.update_own_contact(person, form.cleaned_data)
        messages.success(request, "Saved. Thank you!" if changed else "Nothing needed changing.")
        return redirect("people:profile")
    records = (
        TrainingRecord.objects.filter(volunteer=person, voided_at__isnull=True)
        .select_related("training_type")
        .order_by("training_type__name")
    )
    return render(
        request, "people/profile.html", {"form": form, "person": person, "records": records}
    )


def _turned_off_message(person, shifts) -> str:
    if not shifts:
        return f"{person.get_full_name()} is turned off."
    plural = "shift" if len(shifts) == 1 else "shifts"
    return f"{person.get_full_name()} is turned off and taken off {len(shifts)} {plural}."


@requires("view_contacts")
def deactivate(request, pk):
    """Turn someone off, after showing which future shifts they'll be taken off."""
    person = _person_or_404(pk)
    if not people.can_manage(request.user, person) or person.status != Status.ACTIVE:
        raise PermissionDenied
    if request.method == "POST":
        shifts = people.deactivate(person, by=request.user)
        messages.success(request, _turned_off_message(person, shifts))
        return redirect("people:detail", pk=person.pk)
    upcoming = Signup.objects.filter(
        volunteer=person, status=SignupStatus.CONFIRMED, shift__starts_at__gt=timezone.now()
    ).select_related("shift")
    return render(request, "people/deactivate.html", {"person": person, "upcoming": upcoming})


@requires("view_contacts")
@require_POST
def reactivate(request, pk):
    """Turn someone back on."""
    person = _person_or_404(pk)
    if not people.can_manage(request.user, person):
        raise PermissionDenied
    people.reactivate(person, by=request.user)
    messages.success(request, f"{person.get_full_name()} is turned back on and can sign in.")
    return redirect("people:detail", pk=person.pk)


@requires("manage_staff")
@require_POST
def job_title(request, pk):
    """Change a staff member's job title."""
    person = get_object_or_404(User, pk=pk, role=Role.STAFF)
    form = JobTitleForm(request.POST)
    if form.is_valid():
        people.set_job_title(person, form.cleaned_data["job_title"], by=request.user)
        messages.success(request, "Job title saved.")
    return redirect("people:detail", pk=person.pk)


@requires("view_as_volunteer")
def view_as(request, pk):
    """That volunteer's home page, read-only, under a banner. Nothing on it can be changed."""
    person = get_object_or_404(User.objects.select_related("profile"), pk=pk, role=Role.VOLUNTEER)
    audit.record("volunteer.viewed_as", actor=request.user, target_user=person)
    context = home_context(person, request.GET.get("month"))
    context.update({"readonly": True, "viewer": request.user})
    return render(request, "volunteer/home.html", context)
