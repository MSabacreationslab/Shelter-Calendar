"""Staff screens for building and running the schedule (SPEC §6, Phase 3)."""

from datetime import date, timedelta

from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role, Status, User
from accounts.permissions import PUBLIC, has_capability, requires
from core import audit, errors
from core.forms import post_data
from scheduling import generation, holidays, links, notices, planning, services
from scheduling.forms import (
    WEEKDAYS,
    AssignForm,
    BlackoutForm,
    EditShiftForm,
    EndPatternForm,
    FillForm,
    HolidayForm,
    OneOffShiftForm,
    PatternForm,
    ReasonForm,
    TemplateWeekForm,
    week_start,
)
from scheduling.messages import explain
from scheduling.models import (
    BlackoutPeriod,
    Holiday,
    HolidaySource,
    Shift,
    ShiftPattern,
    ShiftStatus,
    Signup,
    SignupStatus,
    TemplateWeek,
    WaitlistEntry,
    WaitlistStatus,
)


def _parse_day(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@requires("view_full_schedule")
def week(request):
    """Monday to Sunday: every shift, how full it is, holidays and closed days."""
    monday = week_start(_parse_day(request.GET.get("week"), timezone.localdate()))
    sunday = monday + timedelta(days=6)
    shifts = list(planning.shifts_in_range(monday, sunday))
    holiday_names = holidays.holidays_between(monday, sunday)
    closed = {
        day
        for blackout in BlackoutPeriod.objects.filter(start_date__lte=sunday, end_date__gte=monday)
        for day in _days(max(blackout.start_date, monday), min(blackout.end_date, sunday))
    }
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        days.append(
            {
                "date": day,
                "holiday": holidays.holiday_label(holiday_names.get(day, [])),
                "closed": day in closed,
                "shifts": [s for s in shifts if s.local_date == day],
            }
        )
    return render(
        request,
        "scheduling/week.html",
        {
            "days": days,
            "monday": monday,
            "previous": monday - timedelta(weeks=1),
            "next": monday + timedelta(weeks=1),
            "today": timezone.localdate(),
        },
    )


def _days(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _shift_or_404(pk):
    return get_object_or_404(Shift.objects.select_related("required_training", "teaches"), pk=pk)


@requires("view_full_schedule")
def shift_detail(request, pk):
    """Who's on a shift and who's waiting, with the staff actions for it."""
    shift = _shift_or_404(pk)
    signups = shift.signups.filter(status=SignupStatus.CONFIRMED).select_related("volunteer")
    waiting = shift.waitlist.filter(status=WaitlistStatus.WAITING).select_related("volunteer")
    on_shift = {s.volunteer_id for s in signups}
    candidates = (
        User.objects.filter(status=Status.ACTIVE, role__in=[Role.VOLUNTEER, Role.STAFF])
        .exclude(pk__in=on_shift)
        .order_by("first_name", "last_name")
    )
    return render(
        request,
        "scheduling/shift_detail.html",
        {
            "shift": shift,
            "signups": signups,
            "waiting": waiting,
            "spots_left": max(shift.capacity - len(signups), 0),
            "assign_form": AssignForm(people=candidates),
            "can_assign": has_capability(request.user, "assign_volunteers"),
            "can_manage": has_capability(request.user, "manage_shifts"),
            "can_waitlist": has_capability(request.user, "manage_waitlist"),
            "can_record": has_capability(request.user, "record_training"),
            "upcoming": shift.status == ShiftStatus.SCHEDULED and shift.starts_at > timezone.now(),
        },
    )


@requires("assign_volunteers")
@require_POST
def assign(request, pk):
    """Staff add someone to a shift, using the same rules as signing up."""
    shift = _shift_or_404(pk)
    people = User.objects.filter(status=Status.ACTIVE, role__in=[Role.VOLUNTEER, Role.STAFF])
    form = AssignForm(request.POST, people=people)
    if form.is_valid():
        person = form.cleaned_data["person"]
        result = services.sign_up(person, shift, by=request.user)
        if result.ok:
            messages.success(request, f"{person.get_full_name()} is on this shift.")
        else:
            messages.error(request, explain(result, shift=shift, person=person))
    else:
        messages.error(request, "Please choose someone to add.")
    return redirect("scheduling:shift", pk=shift.pk)


@requires("assign_volunteers")
def remove(request, pk, signup_pk):
    """Take someone off a shift, after a confirmation step."""
    signup = get_object_or_404(
        Signup.objects.select_related("shift", "volunteer"), pk=signup_pk, shift_id=pk
    )
    if request.method == "POST":
        services.cancel_signup(signup, by=request.user, reason="Taken off by staff")
        messages.success(request, f"{signup.volunteer.get_full_name()} is off this shift.")
        return redirect("scheduling:shift", pk=pk)
    return render(
        request,
        "components/confirm.html",
        {
            "title": f"Take {signup.volunteer.get_full_name()} off this shift?",
            "summary": [("Shift", notices.describe(signup.shift))],
            "confirm_label": "Yes, take them off",
            "cancel_url": f"/schedule/shifts/{pk}/",
            "danger": True,
        },
    )


@requires("manage_waitlist")
@require_POST
def promote(request, pk, entry_pk):
    """Move someone from the waitlist onto the shift; they get a "good news" email."""
    entry = get_object_or_404(
        WaitlistEntry.objects.select_related("volunteer", "shift"), pk=entry_pk, shift_id=pk
    )
    result = services.promote_from_waitlist(entry, by=request.user)
    if result.ok:
        messages.success(
            request, f"{entry.volunteer.get_full_name()} is on this shift. We've emailed them."
        )
    else:
        messages.error(request, explain(result, shift=entry.shift, person=entry.volunteer))
    return redirect("scheduling:shift", pk=pk)


@requires("manage_waitlist")
@require_POST
def unwait(request, pk, entry_pk):
    """Take someone off the waitlist."""
    entry = get_object_or_404(
        WaitlistEntry.objects.select_related("volunteer"), pk=entry_pk, shift_id=pk
    )
    services.leave_waitlist(entry, by=request.user)
    messages.success(request, f"{entry.volunteer.get_full_name()} is off the waitlist.")
    return redirect("scheduling:shift", pk=pk)


@requires("manage_shifts")
def edit_shift(request, pk):
    """Change one shift. Refused, with names, if it would squeeze out signed-up people."""
    shift = _shift_or_404(pk)
    local_start, local_end = timezone.localtime(shift.starts_at), timezone.localtime(shift.ends_at)
    initial = {
        "title": shift.title,
        "start_time": local_start.time(),
        "end_time": local_end.time(),
        "capacity": shift.capacity,
        "required_training": shift.required_training,
        "notes": shift.notes,
    }
    form = EditShiftForm(post_data(request), initial=initial, shift=shift)
    if request.method == "POST" and form.is_valid():
        result = services.update_shift(shift, by=request.user, **form.changes())
        if result.ok:
            messages.success(request, "Shift saved.")
            return redirect("scheduling:shift", pk=shift.pk)
        messages.error(request, explain(result, shift=shift))
    return render(request, "scheduling/shift_edit.html", {"form": form, "shift": shift})


@requires("manage_shifts")
def cancel_shift(request, pk):
    """Cancel a whole shift with a reason; everyone on it is emailed."""
    shift = _shift_or_404(pk)
    form = ReasonForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        services.cancel_shift(shift, by=request.user, reason=form.cleaned_data["reason"])
        messages.success(request, "The shift is cancelled, and everyone on it has been emailed.")
        return redirect("scheduling:shift", pk=shift.pk)
    people = shift.signups.filter(status=SignupStatus.CONFIRMED).count()
    return render(
        request, "scheduling/shift_cancel.html", {"form": form, "shift": shift, "people": people}
    )


@requires("manage_shifts")
def add_shift(request):
    """A one-off shift, or one that repeats weekly until a date."""
    form = OneOffShiftForm(
        post_data(request), initial={"day": _parse_day(request.GET.get("day"), None)}
    )
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["repeat_until"]:
            with transaction.atomic():
                pattern = planning.add_pattern(form.pattern_data(), by=request.user)
                plan = generation.plan_fill(
                    form.cleaned_data["day"], form.cleaned_data["repeat_until"]
                )
                plan.new = [p for p in plan.new if p.pattern.pk == pattern.pk]
                count = generation.apply_fill(plan, by=request.user)
            messages.success(request, f"Added {count} shifts.")
        else:
            shift = planning.create_shift(form.shift_data(), by=request.user)
            messages.success(request, "Shift added.")
            return redirect("scheduling:shift", pk=shift.pk)
        return redirect(f"/schedule/?week={week_start(form.cleaned_data['day'])}")
    return render(request, "scheduling/shift_add.html", {"form": form})


@requires("manage_shifts")
def templates(request):
    """Template weeks: named sets of repeating shifts."""
    form = TemplateWeekForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        week_obj = planning.add_template_week(form.cleaned_data["name"], by=request.user)
        return redirect("scheduling:template", pk=week_obj.pk)
    return render(
        request, "scheduling/templates.html", {"form": form, "weeks": TemplateWeek.objects.all()}
    )


@requires("manage_shifts")
def template_detail(request, pk):
    """A week grid: each day's repeating shifts."""
    week_obj = get_object_or_404(TemplateWeek, pk=pk)
    today = timezone.localdate()
    patterns = week_obj.patterns.select_related("required_training", "teaches")
    days = [
        {
            "name": name,
            "patterns": [
                p
                for p in patterns
                if p.weekday == number and (p.active_until is None or p.active_until >= today)
            ],
        }
        for number, name in WEEKDAYS
    ]
    return render(request, "scheduling/template_detail.html", {"week": week_obj, "days": days})


@requires("manage_shifts")
def add_pattern(request, pk):
    """Add a repeating shift to a template week."""
    week_obj = get_object_or_404(TemplateWeek, pk=pk)
    form = PatternForm(post_data(request), initial={"weekday": request.GET.get("day", 0)})
    if request.method == "POST" and form.is_valid():
        planning.add_pattern({**form.model_data(), "template_week": week_obj}, by=request.user)
        messages.success(
            request, "Repeating shift added. Use Fill the schedule to create the shifts."
        )
        return redirect("scheduling:template", pk=week_obj.pk)
    return render(request, "scheduling/pattern_form.html", {"form": form, "week": week_obj})


def _back_to(pattern):
    if pattern.template_week_id:
        return redirect("scheduling:template", pk=pattern.template_week_id)
    return redirect("scheduling:week")


@requires("manage_shifts")
def edit_pattern(request, pk):
    """Change a repeating shift; its untouched future shifts follow."""
    pattern = get_object_or_404(ShiftPattern, pk=pk)
    fields = [
        "title",
        "start_time",
        "end_time",
        "capacity",
        "kind",
        "required_training",
        "teaches",
        "notes",
    ]
    form = PatternForm(
        post_data(request), initial={f: getattr(pattern, f) for f in fields}, editing=True
    )
    to_review = None
    if request.method == "POST" and form.is_valid():
        to_review = planning.update_pattern(pattern, form.model_data(), by=request.user)
        if not to_review:
            messages.success(request, "Saved. Future shifts from it are updated.")
            return _back_to(pattern)
    return render(
        request,
        "scheduling/pattern_form.html",
        {"form": form, "pattern": pattern, "week": pattern.template_week, "to_review": to_review},
    )


@requires("manage_shifts")
def end_pattern(request, pk):
    """Stop a repeating shift after a chosen day."""
    pattern = get_object_or_404(ShiftPattern, pk=pk)
    form = EndPatternForm(post_data(request), initial={"last_day": timezone.localdate()})
    to_review = None
    if request.method == "POST" and form.is_valid():
        to_review = planning.end_pattern(pattern, form.cleaned_data["last_day"], by=request.user)
        if not to_review:
            messages.success(request, "Stopped.")
            return _back_to(pattern)
    return render(
        request,
        "scheduling/pattern_end.html",
        {"form": form, "pattern": pattern, "to_review": to_review},
    )


@requires("manage_shifts")
def fill(request):
    """Preview first, then create. Holidays can be kept or skipped one by one."""
    form = FillForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        plan = generation.plan_fill(form.cleaned_data["start"], form.cleaned_data["end"])
        if request.POST.get("step") == "confirm":
            skip = {_parse_day(d, None) for d in request.POST.getlist("skip")} - {None}
            count = generation.apply_fill(plan, skip_days=skip, by=request.user)
            messages.success(request, f"Added {count} shifts.")
            return redirect(f"/schedule/?week={week_start(form.cleaned_data['start'])}")
        return render(request, "scheduling/fill_preview.html", {"form": form, "plan": plan})
    return render(request, "scheduling/fill.html", {"form": form})


@requires("manage_shifts")
def closed_days(request):
    """Blackout periods: filling the schedule skips them."""
    form = BlackoutForm(post_data(request))
    affected = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        _, affected = planning.add_blackout(
            data["start_date"], data["end_date"], data["reason"], by=request.user
        )
        if not affected:
            messages.success(request, "Closed days added.")
            return redirect("scheduling:closed_days")
        form = BlackoutForm()
    upcoming = BlackoutPeriod.objects.filter(end_date__gte=timezone.localdate())
    return render(
        request,
        "scheduling/closed_days.html",
        {"form": form, "blackouts": upcoming, "affected": affected},
    )


@requires("manage_shifts")
@require_POST
def remove_closed_days(request, pk):
    """Reopen closed days."""
    planning.remove_blackout(get_object_or_404(BlackoutPeriod, pk=pk), by=request.user)
    messages.success(request, "Those days are open again. Fill the schedule to add their shifts.")
    return redirect("scheduling:closed_days")


@requires("manage_shifts")
def holiday_list(request):
    """This year's and next year's holidays: add the shelter's own, hide ones it doesn't observe."""
    form = HolidayForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        holidays.add_shelter_holiday(
            form.cleaned_data["day"], form.cleaned_data["name"], by=request.user
        )
        messages.success(request, "Holiday added.")
        return redirect("scheduling:holidays")
    today = timezone.localdate()
    upcoming = Holiday.objects.filter(date__gte=today, date__lte=date(today.year + 1, 12, 31))
    return render(
        request,
        "scheduling/holidays.html",
        {"form": form, "holidays": upcoming, "shelter_source": HolidaySource.SHELTER},
    )


@requires("manage_shifts")
@require_POST
def toggle_holiday(request, pk):
    """Hide a holiday or show it again."""
    holiday = get_object_or_404(Holiday, pk=pk)
    holidays.set_hidden(holiday, not holiday.hidden, by=request.user)
    return redirect("scheduling:holidays")


@requires("manage_shifts")
@require_POST
def remove_holiday(request, pk):
    """Remove one of the shelter's own holidays."""
    holiday = get_object_or_404(Holiday, pk=pk, source=HolidaySource.SHELTER)
    holidays.remove_shelter_holiday(holiday, by=request.user)
    return redirect("scheduling:holidays")


@requires(PUBLIC)
def orientation_conflict(request, token):
    """From the welcome email: tell staff the orientation time doesn't work. No sign-in needed."""
    try:
        signup = Signup.objects.select_related("shift", "volunteer").get(
            pk=links.signup_from_conflict_token(token)
        )
    except (signing.BadSignature, Signup.DoesNotExist, KeyError, TypeError, ValueError):
        return render(
            request, "accounts/link_invalid.html", {"error": errors.LINK_EXPIRED}, status=410
        )
    shift = signup.shift
    if request.method == "POST":
        if signup.conflict_reported_at is None:
            with transaction.atomic():
                signup.conflict_reported_at = timezone.now()
                signup.save(update_fields=["conflict_reported_at"])
                audit.record(
                    "orientation.conflict_reported",
                    actor=None,
                    target_user=signup.volunteer,
                    target_repr=str(shift),
                )
                transaction.on_commit(lambda: notices.orientation_conflict(signup))
        return render(request, "scheduling/conflict_done.html", {"signup": signup, "shift": shift})
    return render(request, "scheduling/conflict_confirm.html", {"signup": signup, "shift": shift})
