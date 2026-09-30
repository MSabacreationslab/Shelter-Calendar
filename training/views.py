"""Staff screens for training (SPEC §6, Phase 5)."""

from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from accounts.permissions import has_capability, requires
from core.forms import post_data
from scheduling.models import Shift, ShiftKind, SignupStatus
from training import services
from training.forms import (
    AttendanceForm,
    NeedForm,
    RecordForm,
    TrainingTypeForm,
    VoidForm,
    active_people,
)
from training.models import TrainingNeed, TrainingRecord, TrainingType

SESSIONS_AHEAD = timedelta(days=60)
SESSIONS_BACK = timedelta(days=30)


def _person_or_404(pk):
    return get_object_or_404(
        User.objects.select_related("profile"), pk=pk, role__in=[Role.VOLUNTEER, Role.STAFF]
    )


@requires("record_training")
def overview(request):
    """Recent and upcoming sessions, and the list of trainings with how many have each."""
    now = timezone.now()
    sessions = (
        Shift.objects.filter(
            kind=ShiftKind.TRAINING,
            starts_at__gte=now - SESSIONS_BACK,
            starts_at__lte=now + SESSIONS_AHEAD,
        )
        .select_related("teaches")
        .annotate(
            people=Count(
                "signups", filter=Q(signups__status=SignupStatus.CONFIRMED), distinct=True
            ),
            recorded=Count(
                "training_records",
                filter=Q(training_records__voided_at__isnull=True),
                distinct=True,
            ),
        )
        .order_by("starts_at")
    )
    types = [
        {
            "type": t,
            "trained": TrainingRecord.objects.filter(training_type=t, voided_at__isnull=True)
            .values("volunteer")
            .distinct()
            .count(),
            "waiting": TrainingNeed.objects.filter(
                training_type=t, resolved_at__isnull=True
            ).count(),
        }
        for t in TrainingType.objects.order_by("-active", "name")
    ]
    form = TrainingTypeForm(post_data(request))
    if request.method == "POST":
        if not has_capability(request.user, "manage_trainings"):
            return redirect("training:overview")
        if form.is_valid():
            services.add_type(
                form.cleaned_data["name"],
                is_orientation=form.cleaned_data.get("is_orientation", False),
                by=request.user,
            )
            messages.success(request, f"“{form.cleaned_data['name']}” is on the list.")
            return redirect("training:overview")
    return render(
        request,
        "training/overview.html",
        {
            "past": [s for s in sessions if s.starts_at <= now],
            "upcoming": [s for s in sessions if s.starts_at > now],
            "types": types,
            "form": form,
            "can_manage": has_capability(request.user, "manage_trainings"),
        },
    )


@requires("manage_trainings")
def rename_type(request, pk):
    """Rename a training."""
    training_type = get_object_or_404(TrainingType, pk=pk)
    form = TrainingTypeForm(
        post_data(request), initial={"name": training_type.name}, training_type=training_type
    )
    if request.method == "POST" and form.is_valid():
        services.rename_type(training_type, form.cleaned_data["name"], by=request.user)
        messages.success(request, "Training renamed.")
        return redirect("training:overview")
    return render(
        request, "training/type_edit.html", {"form": form, "training_type": training_type}
    )


@requires("manage_trainings")
@require_POST
def toggle_type(request, pk):
    """Take a training off the lists, or put it back."""
    training_type = get_object_or_404(TrainingType, pk=pk)
    services.set_type_active(training_type, not training_type.active, by=request.user)
    return redirect("training:overview")


@requires("record_training")
def session(request, pk):
    """Tick who came to a session; one Save records everyone."""
    shift = get_object_or_404(
        Shift.objects.select_related("teaches"), pk=pk, kind=ShiftKind.TRAINING
    )
    signed_up = User.objects.filter(signups__shift=shift, signups__status=SignupStatus.CONFIRMED)
    still_need = User.objects.filter(
        training_needs__training_type=shift.teaches, training_needs__resolved_at__isnull=True
    )
    already = set(
        TrainingRecord.objects.filter(session=shift, voided_at__isnull=True).values_list(
            "volunteer_id", flat=True
        )
    )
    candidates = (active_people().filter(Q(pk__in=signed_up) | Q(pk__in=still_need))).exclude(
        pk__in=already
    )
    others = active_people().exclude(pk__in=candidates).exclude(pk__in=already)
    initial = {
        "attended": list(signed_up.exclude(pk__in=already).values_list("pk", flat=True)),
        "completed_on": min(shift.local_date, timezone.localdate()),
        "trainer": request.user if request.user.is_staff_member else None,
    }
    form = AttendanceForm(post_data(request), initial=initial, candidates=candidates, others=others)
    if request.method == "POST" and form.is_valid():
        records = services.record_session(
            shift,
            form.people(),
            completed_on=form.cleaned_data["completed_on"],
            trainer=form.cleaned_data["trainer"],
            by=request.user,
            notes=form.cleaned_data["notes"],
        )
        count = len(records)
        messages.success(
            request,
            f"{shift.teaches.name} recorded for {count} {'person' if count == 1 else 'people'}.",
        )
        return redirect("training:overview")
    recorded = User.objects.filter(pk__in=already).order_by("first_name", "last_name")
    return render(
        request,
        "training/session.html",
        {
            "shift": shift,
            "form": form,
            "recorded": recorded,
            "not_started": shift.starts_at > timezone.now(),
        },
    )


@requires("record_training")
def add_record(request):
    """One training done outside a session in the app, such as before the app existed."""
    initial = {"completed_on": timezone.localdate()}
    person_pk = request.GET.get("person")
    if person_pk and person_pk.isdigit():
        initial["person"] = person_pk
    form = RecordForm(post_data(request), initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        services.record_one(
            data["person"],
            data["training_type"],
            completed_on=data["completed_on"],
            trainer=data["trainer"],
            by=request.user,
            notes=data["notes"],
        )
        messages.success(
            request, f"{data['training_type'].name} recorded for {data['person'].get_full_name()}."
        )
        return redirect("people:detail", pk=data["person"].pk)
    return render(request, "training/record_form.html", {"form": form})


@requires("record_training")
def void(request, pk):
    """Mark a mistaken record, with a reason. It stays in the history."""
    record = get_object_or_404(
        TrainingRecord.objects.select_related("volunteer", "training_type"),
        pk=pk,
        voided_at__isnull=True,
    )
    form = VoidForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        lost_access = services.void_record(
            record, reason=form.cleaned_data["reason"], by=request.user
        )
        messages.success(request, "That record is marked as a mistake.")
        if lost_access:
            messages.warning(
                request,
                f"{record.volunteer.get_short_name()} can't take no-training shifts now, because "
                "orientation isn't recorded. You can allow it again below.",
            )
        return redirect("people:detail", pk=record.volunteer_id)
    return render(request, "training/void.html", {"record": record, "form": form})


@requires("record_training")
@require_POST
def add_need(request, pk):
    """Note a training someone still needs."""
    person = _person_or_404(pk)
    form = NeedForm(request.POST, person=person)
    if form.is_valid():
        services.add_need(person, form.cleaned_data["training_type"], by=request.user)
        messages.success(request, f"Added: needs {form.cleaned_data['training_type'].name}.")
    return redirect("people:detail", pk=person.pk)


@requires("record_training")
@require_POST
def remove_need(request, pk):
    """They don't need that training after all."""
    need = get_object_or_404(TrainingNeed, pk=pk, resolved_at__isnull=True)
    services.remove_need(need, by=request.user)
    return redirect("people:detail", pk=need.volunteer_id)


@requires("edit_volunteers")
@require_POST
def no_training(request, pk):
    """Allow or stop someone taking shifts that need no training."""
    person = _person_or_404(pk)
    allowed = request.POST.get("allowed") == "yes"
    services.set_no_training_allowed(person, allowed, by=request.user)
    return redirect("people:detail", pk=person.pk)
