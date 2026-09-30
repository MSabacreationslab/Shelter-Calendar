"""Volunteer screens: home calendar, day page, find a shift, sign up, cancel, waitlist."""

from datetime import date

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import requires
from core.context_processors import shelter_details
from core.forms import post_data
from scheduling import calendar_view as cal
from scheduling import services as booking
from scheduling.forms import CancelForm
from scheduling.messages import explain
from scheduling.models import (
    RequestStatus,
    Shift,
    ShiftStatus,
    Signup,
    SignupRequest,
    SignupStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from training import eligibility


def _my_signup(user, shift):
    return Signup.objects.filter(shift=shift, volunteer=user, status=SignupStatus.CONFIRMED).first()


def _my_wait(user, shift):
    return WaitlistEntry.objects.filter(
        shift=shift, volunteer=user, status=WaitlistStatus.WAITING
    ).first()


def _my_request(user, shift):
    return SignupRequest.objects.filter(
        shift=shift, volunteer=user, status=RequestStatus.WAITING
    ).first()


def _mark_approval(user, shifts):
    """Tag each shift with whether this person has to ask first."""
    for shift in shifts:
        shift.ask_first = booking.needs_approval(user, shift)
    return shifts


def home_context(person, month=None) -> dict:
    """Everything a volunteer's home page shows, for them or for staff viewing as them."""
    first = cal.month_start(month)
    upcoming = list(cal.my_signups(person)[:20])
    return {
        "person": person,
        "greeting": cal.greeting(),
        "next_signup": upcoming[0] if upcoming else None,
        "upcoming": upcoming,
        "asked": list(cal.my_requests(person)),
        "weeks": cal.month_grid(person, first),
        "month": cal.month_label(first),
        "previous": cal.shift_month(first, -1),
        "next": cal.shift_month(first, 1),
        "previous_label": cal.month_label(cal.shift_month(first, -1)),
        "next_label": cal.month_label(cal.shift_month(first, 1)),
        "day_names": cal.DAY_NAMES,
    }


@requires("view_own_schedule")
def my_shifts(request):
    """A volunteer's home: next shift, the month calendar, and upcoming shifts."""
    context = home_context(request.user, request.GET.get("month"))
    return render(request, "volunteer/home.html", context)


@requires("view_own_schedule")
def day(request, day):
    """One day: shifts I'm on (with Cancel) and shifts I could take."""
    try:
        chosen = date.fromisoformat(day)
    except ValueError as exc:
        raise Http404 from exc
    mine, others, waiting = cal.day_shifts(request.user, chosen)
    asked = set(
        cal.my_requests(request.user)
        .filter(shift__local_date=chosen)
        .values_list("shift_id", flat=True)
    )
    now = timezone.now()
    return render(
        request,
        "volunteer/day.html",
        {
            "day": chosen,
            "mine": mine,
            "others": _mark_approval(
                request.user,
                [s for s in others if s.status == ShiftStatus.SCHEDULED and s.starts_at > now],
            ),
            "waiting": waiting,
            "asked": asked,
            "month": chosen.strftime("%Y-%m"),
        },
    )


@requires("view_own_schedule")
def find(request):
    """Open shifts for the next two weeks, as a plain list."""
    days = [(day, _mark_approval(request.user, s)) for day, s in cal.find_list(request.user)]
    return render(request, "volunteer/find.html", {"days": days})


@requires("view_own_schedule")
def shift_page(request, pk):
    """One shift from the volunteer's side, with the one action that fits."""
    shift = get_object_or_404(Shift.objects.select_related("required_training", "teaches"), pk=pk)
    signup = _my_signup(request.user, shift)
    wait = _my_wait(request.user, shift)
    asked = None if signup else _my_request(request.user, shift)
    reason = None if signup else eligibility.why_not(request.user, shift)
    filled = booking.confirmed_count(shift)
    return render(
        request,
        "volunteer/shift.html",
        {
            "shift": shift,
            "signup": signup,
            "wait": wait,
            "asked": asked,
            "ask_first": booking.needs_approval(request.user, shift),
            "reason": explain(
                booking.Result.fail(booking.Problem.NOT_ELIGIBLE, reason=reason), shift=shift
            )
            if reason and reason not in (eligibility.CANCELLED, eligibility.STARTED)
            else None,
            "closed": shift.status != ShiftStatus.SCHEDULED or shift.starts_at <= timezone.now(),
            "full": filled >= shift.capacity,
            "spots_left": max(shift.capacity - filled, 0),
            "started": shift.starts_at <= timezone.now(),
        },
    )


@requires("sign_up_self")
def sign_up(request, pk):
    """Step 1 shows exactly what you're signing up for; step 2 (the POST) books it."""
    shift = get_object_or_404(Shift, pk=pk)
    if request.method == "POST":
        result = booking.sign_up(request.user, shift)
        if result.ok:
            return redirect("shifts:signed_up", pk=shift.pk)
        if result.problem == booking.Problem.NEEDS_APPROVAL:
            return redirect("shifts:ask", pk=shift.pk)
        messages.error(request, explain(result, shift=shift))
        return redirect("shifts:shift", pk=shift.pk)
    if _my_signup(request.user, shift):
        return redirect("shifts:signed_up", pk=shift.pk)
    if booking.needs_approval(request.user, shift):
        return redirect("shifts:ask", pk=shift.pk)
    return render(request, "volunteer/sign_up.html", {"shift": shift})


@requires("sign_up_self")
def ask(request, pk):
    """Step 1 restates the shift; step 2 (the POST) sends the request to staff."""
    shift = get_object_or_404(Shift, pk=pk)
    if request.method == "POST":
        result = booking.ask_to_join(request.user, shift)
        if result.ok:
            if result.signup_request:
                messages.success(
                    request,
                    "We've asked the volunteer team. We'll email you when they answer.",
                )
        elif result.problem == booking.Problem.NO_APPROVAL_NEEDED:
            return redirect("shifts:sign_up", pk=shift.pk)
        else:
            messages.error(request, explain(result, shift=shift))
        return redirect("shifts:shift", pk=shift.pk)
    if _my_signup(request.user, shift) or _my_request(request.user, shift):
        return redirect("shifts:shift", pk=shift.pk)
    if not booking.needs_approval(request.user, shift):
        return redirect("shifts:sign_up", pk=shift.pk)
    return render(request, "volunteer/ask.html", {"shift": shift})


@requires("sign_up_self")
@require_POST
def take_back(request, pk):
    """Take back a request to join a shift."""
    shift = get_object_or_404(Shift, pk=pk)
    asked = _my_request(request.user, shift)
    if asked:
        booking.withdraw_request(asked, by=request.user)
        messages.success(request, "You've taken back your request.")
    return redirect("shifts:shift", pk=shift.pk)


@requires("view_own_schedule")
def signed_up(request, pk):
    """The success page, with Add to my calendar."""
    shift = get_object_or_404(Shift, pk=pk)
    if not _my_signup(request.user, shift):
        return redirect("shifts:shift", pk=shift.pk)
    return render(request, "volunteer/signed_up.html", {"shift": shift})


@requires("view_own_schedule")
def calendar_file(request, pk):
    """An .ics file for a shift you're on."""
    shift = get_object_or_404(Shift, pk=pk)
    if not _my_signup(request.user, shift):
        raise Http404
    response = HttpResponse(
        cal.ics(shift, shelter_details()["name"]), content_type="text/calendar; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="volunteer-shift.ics"'
    return response


@requires("cancel_own_signup")
def cancel(request, pk):
    """Cancel your own shift. Inside the window it's "I can't make it" and staff are told."""
    shift = get_object_or_404(Shift, pk=pk)
    signup = _my_signup(request.user, shift)
    if signup is None:
        return redirect("shifts:shift", pk=shift.pk)
    if shift.starts_at <= timezone.now():
        return render(request, "volunteer/cancel_too_late.html", {"shift": shift})
    late = booking.is_late(shift)
    form = CancelForm(post_data(request))
    if request.method == "POST" and form.is_valid():
        result = booking.cancel_signup(signup, by=request.user, reason=form.cleaned_data["reason"])
        if not result.ok:
            messages.error(request, explain(result, shift=shift))
            return redirect("shifts:shift", pk=shift.pk)
        if result.late:
            messages.success(request, "Thanks for letting us know. We've told the volunteer team.")
        else:
            messages.success(request, f"You're no longer signed up for {shift.title}.")
        return redirect("shifts:home")
    return render(request, "volunteer/cancel.html", {"shift": shift, "late": late, "form": form})


@requires("sign_up_self")
@require_POST
def join_waitlist(request, pk):
    """Wait for a spot on a full shift."""
    shift = get_object_or_404(Shift, pk=pk)
    result = booking.join_waitlist(request.user, shift)
    if result.ok:
        messages.success(
            request,
            "You're on the waitlist. If a spot opens, the volunteer team will let you know.",
        )
    else:
        messages.error(request, explain(result, shift=shift))
    return redirect("shifts:shift", pk=shift.pk)


@requires("sign_up_self")
@require_POST
def leave_waitlist(request, pk):
    """Stop waiting for a spot."""
    shift = get_object_or_404(Shift, pk=pk)
    wait = _my_wait(request.user, shift)
    if wait:
        booking.leave_waitlist(wait, by=request.user)
        messages.success(request, "You're off the waitlist.")
    return redirect("shifts:shift", pk=shift.pk)
