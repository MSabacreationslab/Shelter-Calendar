"""Staff screens: the volunteer list, adding and editing volunteers, setup links, skills."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts import people
from accounts.models import Role, Skill, Status, User
from accounts.people_forms import AddVolunteerForm, SkillForm, VolunteerDetailsForm, details_initial
from accounts.permissions import has_capability, requires
from training.models import TrainingNeed, TrainingRecord

SETUP_TEMPLATES = ["welcome", "new_pin"]


def _person_or_404(pk):
    """Volunteers and staff; the Admin never appears in staff screens."""
    return get_object_or_404(
        User.objects.select_related("profile"), pk=pk, role__in=[Role.VOLUNTEER, Role.STAFF]
    )


@requires("view_contacts")
def volunteer_list(request):
    """Everyone who volunteers, A to Z. The filter box works in the browser, so names never
    end up in web addresses or logs."""
    show_inactive = request.GET.get("show") == "all"
    volunteers = User.objects.filter(role=Role.VOLUNTEER).select_related("profile")
    if not show_inactive:
        volunteers = volunteers.filter(status=Status.ACTIVE)
    return render(
        request,
        "people/list.html",
        {"volunteers": volunteers, "show_inactive": show_inactive},
    )


@requires("add_volunteers")
def add_volunteer(request):
    """One page, one Save: details, sign-in name, training, then the welcome email."""
    form = AddVolunteerForm(request.POST or None)
    duplicates = []
    if request.method == "POST" and form.is_valid():
        duplicates = form.possible_duplicates()
        if not duplicates or request.POST.get("add_anyway"):
            person = people.add_volunteer(form.cleaned_data, added_by=request.user)
            messages.success(
                request,
                f"{person.get_full_name()} is added. We've emailed them a link to choose a PIN.",
            )
            return redirect("people:detail", pk=person.pk)
    return render(request, "people/add.html", {"form": form, "duplicates": duplicates})


@requires("view_contacts")
def person_detail(request, pk):
    """Everything about one person, plus the latest setup email and whether it went out."""
    person = _person_or_404(pk)
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
        "can_edit": has_capability(request.user, "edit_volunteers"),
        "can_send_link": people.can_send_link(request.user, person),
    }
    return render(request, "people/detail.html", context)


@requires("edit_volunteers")
def edit_person(request, pk):
    """Change someone's details. Only the fields that changed go in the change log."""
    person = _person_or_404(pk)
    form = VolunteerDetailsForm(
        request.POST or None, initial=details_initial(person), person=person
    )
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
    form = SkillForm(request.POST or None)
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
    form = SkillForm(request.POST or None, initial={"name": skill.name}, skill=skill)
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
