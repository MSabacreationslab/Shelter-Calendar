"""Sign in, sign out, and choose a PIN from a setup link."""

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts import services
from accounts.forms import SetPinForm, SignInForm
from accounts.permissions import PUBLIC, SIGNED_IN, requires
from accounts.services import Outcome
from core import errors


def _safe_next(request) -> str:
    """Where to go after signing in: the page they asked for, if it's on this site."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return "/"


@requires(PUBLIC)
def sign_in(request):
    """Name and PIN, with plain messages for every lockout rule."""
    if request.user.is_authenticated:
        return redirect("home")
    form = SignInForm(request.POST or None)
    problem = None
    show_forgot_hint = False
    if request.method == "POST" and form.is_valid():
        result = services.sign_in(request, form.cleaned_data["name"], form.cleaned_data["pin"])
        if result.outcome == Outcome.SIGNED_IN:
            return redirect(_safe_next(request))
        problem = result.outcome.value
        show_forgot_hint = result.show_forgot_hint
    return render(
        request,
        "accounts/sign_in.html",
        {
            "form": form,
            "problem": problem,
            "show_forgot_hint": show_forgot_hint,
            "next": _safe_next(request),
        },
    )


@requires(SIGNED_IN)
@require_POST
def sign_out(request):
    """Sign out (a button, never a link, so nothing can sign someone out by accident)."""
    logout(request)
    messages.success(request, "You're signed out. See you next time!")
    return redirect("accounts:sign_in")


@requires(PUBLIC)
def setup_pin(request, token):
    """Choose a PIN from a one-time link. Opening the page never uses the link up."""
    link = services.find_valid_link(token)
    if link is None:
        return render(
            request, "accounts/link_invalid.html", {"error": errors.LINK_EXPIRED}, status=410
        )
    form = SetPinForm(request.POST or None, user=link.user)
    if request.method == "POST" and form.is_valid():
        user = services.set_pin_from_link(token, form.cleaned_data["pin"])
        if user is None:
            return render(
                request, "accounts/link_invalid.html", {"error": errors.LINK_EXPIRED}, status=410
            )
        services.sign_in_after_setup(request, user)
        messages.success(request, "Your PIN is set, and you're signed in. Welcome!")
        return redirect("home")
    return render(request, "accounts/setup_pin.html", {"form": form, "person": link.user})
