"""Sending the Sunday digest and the monthly summary (SPEC §6, Phase 7).

Each report claims its period in SentReport before sending, so a double trigger
(two cron runs, or a run by hand after the cron) never sends it twice.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import ShelterSettings
from notifications import email
from reports import data
from reports.models import ReportKind, SentReport

NO_RECIPIENTS = "No notification emails are set. Add them in Settings."
ALREADY_SENT = "Already sent for this period. Use --again to send it again."


@dataclass
class SendResult:
    sent: int
    reason: str = ""


def _claim(kind, period_start, recipients, again) -> bool:
    """Record that this period is being sent. False if it already was (and `again` is off)."""
    with transaction.atomic():
        record, created = SentReport.objects.select_for_update().get_or_create(
            kind=kind, period_start=period_start, defaults={"recipients": len(recipients)}
        )
        if not created:
            if not again:
                return False
            record.sent_at = timezone.now()
            record.recipients = len(recipients)
            record.save(update_fields=["sent_at", "recipients"])
    return True


def _send(kind, period_start, template, context, again) -> SendResult:
    recipients = ShelterSettings.load().notify_email_list
    if not recipients:
        return SendResult(0, NO_RECIPIENTS)
    if not _claim(kind, period_start, recipients, again):
        return SendResult(0, ALREADY_SENT)
    for address in recipients:
        email.send(template, to=address, context=context)
    return SendResult(len(recipients))


def send_weekly_digest(today=None, *, again=False) -> SendResult:
    """Next week by day and by volunteer, plus the last 7 days' cancellations."""
    today = today or timezone.localdate()
    start = data.next_monday(today)
    now = timezone.now()
    context = {
        "week": data.week_ahead(start),
        "cancellations": data.cancellations_between(now - timedelta(days=7), now),
    }
    return _send(ReportKind.WEEKLY, start, "weekly_digest", context, again)


def send_monthly_summary(today=None, *, again=False) -> SendResult:
    """Last month in numbers."""
    today = today or timezone.localdate()
    first = data.previous_month_start(today)
    context = {"summary": data.month_summary(first)}
    return _send(ReportKind.MONTHLY, first, "monthly_summary", context, again)
