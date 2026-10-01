"""The numbers on the Admin's Usage and Hotspots pages. Every function looks back `days` days."""

from collections import Counter, defaultdict, deque
from datetime import timedelta

from django.db.models import Avg, Count, F, Max, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from accounts.models import LoginAttempt
from core import audit
from core.models import AuditEvent
from insights.models import PageView, Problem

PERIODS = (7, 30, 90)
SIGNED_UP = ["shift.signed_up", "shift.added_by_staff", "request.approved"]
CANCELLED = ["shift.cancelled"]
# Opening the same page this many times in a row within the window suggests someone is lost.
REPEATS = 3
REPEAT_WINDOW = timedelta(minutes=10)
TOP = 15

# Plain names for the pages, so the Admin doesn't have to read route names.
PAGE_NAMES = {
    "home": "Home (calendar or dashboard)",
    "accounts:sign_in": "Sign in",
    "accounts:sign_out": "Sign out",
    "accounts:setup_pin": "Choose a PIN (setup link)",
    "shifts:home": "My shifts (calendar)",
    "shifts:day": "A day on the calendar",
    "shifts:find": "Find a shift",
    "shifts:shift": "A shift (volunteer view)",
    "shifts:sign_up": "Sign up for a shift",
    "shifts:signed_up": "Signed up (success page)",
    "shifts:calendar_file": "Add to my calendar",
    "shifts:cancel": "Cancel my shift",
    "shifts:join_waitlist": "Join a waitlist",
    "shifts:leave_waitlist": "Leave a waitlist",
    "shifts:ask": "Request a shift",
    "shifts:take_back": "Cancel a request",
    "people:profile": "My profile",
    "people:list": "Volunteers list",
    "people:add": "Add a volunteer",
    "people:detail": "A volunteer's page",
    "people:edit": "Edit a volunteer",
    "people:send_link": "Send a setup link",
    "people:deactivate": "Turn someone off",
    "people:reactivate": "Turn someone back on",
    "people:job_title": "Change a job title",
    "people:view_as": "View the app as someone",
    "people:skills": "Skills list",
    "people:edit_skill": "Rename a skill",
    "people:toggle_skill": "Turn a skill on or off",
    "scheduling:week": "Schedule (week)",
    "scheduling:add_shift": "Add a shift",
    "scheduling:fill": "Fill the schedule",
    "scheduling:shift": "A shift (staff view)",
    "scheduling:assign": "Add someone to a shift",
    "scheduling:remove": "Take someone off a shift",
    "scheduling:promote": "Move someone off the waitlist",
    "scheduling:unwait": "Take someone off a waitlist",
    "scheduling:edit_shift": "Change a shift",
    "scheduling:cancel_shift": "Cancel a shift",
    "scheduling:templates": "Template weeks",
    "scheduling:template": "A template week",
    "scheduling:add_pattern": "Add a repeating shift",
    "scheduling:edit_pattern": "Change a repeating shift",
    "scheduling:end_pattern": "Stop a repeating shift",
    "scheduling:closed_days": "Closed days",
    "scheduling:remove_closed_days": "Reopen closed days",
    "scheduling:holidays": "Holidays",
    "scheduling:toggle_holiday": "Show or hide a holiday",
    "scheduling:remove_holiday": "Remove a holiday",
    "scheduling:orientation_conflict": "Orientation time doesn't work (email link)",
    "scheduling:approvals": "Shift approvals",
    "scheduling:approve": "Approve a request",
    "scheduling:decline": "Say no to a request",
    "training:overview": "Training",
    "training:add_record": "Record training",
    "training:rename_type": "Rename a training",
    "training:toggle_type": "Turn a training on or off",
    "training:session": "Record a training session",
    "training:void": "Mark training as a mistake",
    "training:add_need": "Add a training someone needs",
    "training:remove_need": "Remove a training someone needs",
    "training:no_training": "Allow no-training shifts",
    "reports:report": "Reports",
    "reports:download": "Download a report",
    "dashboard:admin": "Admin",
    "dashboard:change_log": "Change log",
    "dashboard:settings": "Shelter settings",
    "dashboard:staff": "Staff list",
    "dashboard:add_staff": "Add a staff member",
    "insights:usage": "Usage",
    "insights:hotspots": "Hotspots",
    "insights:problems": "Problems",
    "insights:test_alert": "Send a test alert",
    "elsewhere": "Another website or an email",
}


def page_name(route: str) -> str:
    """A plain name for a page, or the route itself if it's new."""
    return PAGE_NAMES.get(route, route)


def period(value) -> int:
    """The ?days= choice, defaulting to 30."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 30
    return days if days in PERIODS else 30


def _since(days):
    return timezone.now() - timedelta(days=days)


def _people(views) -> int:
    return views.exclude(user=None).values("user").distinct().count()


def _with_bars(rows, key):
    """Add a 0–100 `bar` to each row, relative to the biggest."""
    biggest = max((row[key] for row in rows), default=0) or 1
    for row in rows:
        row["bar"] = round(row[key] * 100 / biggest)
    return rows


def usage(days: int) -> dict:
    """Who used the app, how much, when and on what."""
    start = _since(days)
    views = PageView.objects.filter(at__gte=start)
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    attempts = LoginAttempt.objects.filter(created_at__gte=start)
    events = AuditEvent.objects.filter(created_at__gte=start)
    pages = views.count()

    devices = list(views.values("device").annotate(n=Count("id")).order_by("-n"))
    for row in devices:
        row["share"] = round(row["n"] * 100 / pages) if pages else 0

    local = timezone.get_current_timezone()
    by_day = {
        row["day"]: row
        for row in views.annotate(day=TruncDate("at", tzinfo=local))
        .values("day")
        .annotate(pages=Count("id"), people=Count("user", distinct=True))
    }
    signed = Counter(
        events.filter(action__in=SIGNED_UP)
        .annotate(day=TruncDate("created_at", tzinfo=local))
        .values_list("day", flat=True)
    )
    cancelled = Counter(
        events.filter(action__in=CANCELLED)
        .annotate(day=TruncDate("created_at", tzinfo=local))
        .values_list("day", flat=True)
    )
    today = timezone.localdate()
    daily = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        row = by_day.get(day, {})
        daily.append(
            {
                "day": day,
                "people": row.get("people", 0),
                "pages": row.get("pages", 0),
                "signed_up": signed[day],
                "cancelled": cancelled[day],
            }
        )

    hours = Counter(
        dict(
            views.annotate(hour=ExtractHour("at", tzinfo=local))
            .values("hour")
            .annotate(n=Count("id"))
            .values_list("hour", "n")
        )
    )
    busiest = [{"hour": hour, "n": hours[hour]} for hour in range(6, 23)]

    return {
        "people_today": _people(PageView.objects.filter(at__gte=midnight)),
        "people_week": _people(PageView.objects.filter(at__gte=_since(7))),
        "people": _people(views),
        "volunteers": _people(views.filter(role="volunteer")),
        "staff": _people(views.filter(role__in=["staff", "admin"])),
        "pages": pages,
        "sign_ins": attempts.filter(succeeded=True).count(),
        "wrong_pins": attempts.filter(succeeded=False).count(),
        "signed_up": events.filter(action__in=SIGNED_UP).count(),
        "cancelled": events.filter(action__in=CANCELLED).count(),
        "devices": devices,
        "daily": _with_bars(daily, "pages"),
        "hours": _with_bars(busiest, "n"),
    }


def _repeat_visits(views) -> list[dict]:
    """Pages someone opened REPEATS+ times within REPEAT_WINDOW (even with other pages between):
    a sign they went back and forth looking for something."""
    rows = (
        views.filter(method="GET", status=200)
        .exclude(user=None)
        .order_by("user_id", "route", "at")
        .values_list("user_id", "route", "at")
    )
    bursts, people = Counter(), defaultdict(set)
    key, window = None, deque()
    for user_id, route, at in rows.iterator():
        if (user_id, route) != key:
            key, window = (user_id, route), deque()
        window.append(at)
        while at - window[0] > REPEAT_WINDOW:
            window.popleft()
        if len(window) >= REPEATS:
            bursts[route] += 1
            people[route].add(user_id)
            window.clear()
    return [
        {"route": route, "name": page_name(route), "times": times, "people": len(people[route])}
        for route, times in bursts.most_common(TOP)
    ]


def hotspots(days: int) -> dict:
    """What people do most, where they go next, and where they struggle."""
    views = PageView.objects.filter(at__gte=_since(days))
    pages = list(
        views.filter(method="GET")
        .values("route")
        .annotate(visits=Count("id"), people=Count("user", distinct=True))
        .order_by("-visits")[:TOP]
    )
    actions = list(
        AuditEvent.objects.filter(created_at__gte=_since(days))
        .values("action")
        .annotate(n=Count("id"))
        .order_by("-n")[:TOP]
    )
    paths = list(
        views.filter(method="GET")
        .exclude(came_from="")
        .exclude(came_from=F("route"))
        .values("came_from", "route")
        .annotate(n=Count("id"))
        .order_by("-n")[:TOP]
    )
    forms = list(
        views.filter(method="POST")
        .values("route")
        .annotate(sent=Count("id"), problems=Count("id", filter=Q(form_problem=True)))
        .filter(problems__gt=0)
        .order_by("-problems")[:TOP]
    )
    slow = list(
        views.values("route")
        .annotate(n=Count("id"), average=Avg("duration_ms"), worst=Max("duration_ms"))
        .filter(n__gte=5)
        .order_by("-average")[:10]
    )
    for row in pages + forms + slow:
        row["name"] = page_name(row["route"])
    for row in forms:
        row["rate"] = round(row["problems"] * 100 / row["sent"])
    for row in actions:
        row["name"] = audit.ACTIONS.get(row["action"], row["action"])
    for row in paths:
        row["from_name"] = page_name(row["came_from"])
        row["to_name"] = page_name(row["route"])
    return {
        "pages": _with_bars(pages, "visits"),
        "actions": _with_bars(actions, "n"),
        "paths": paths,
        "forms": forms,
        "repeats": _repeat_visits(views),
        "slow": slow,
    }


def problems(days: int) -> dict:
    """Recent problems, newest first, and a count by code."""
    recent = Problem.objects.filter(at__gte=_since(days)).select_related("user")
    return {
        "by_code": list(recent.values("code").annotate(n=Count("id")).order_by("-n")),
        "latest": list(recent[:100]),
        "total": recent.count(),
    }
