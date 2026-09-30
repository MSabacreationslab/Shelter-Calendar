"""Sending email. Every email has a plain-text and a large-type HTML version."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from core.context_processors import shelter_details
from notifications.models import EmailLog

logger = logging.getLogger(__name__)


def send(template_key: str, *, to: str, context: dict, related_user=None) -> EmailLog:
    """Render emails/<key>_subject.txt, <key>.txt and <key>.html and send them.

    Never raises: a failed send is written to EmailLog and shown to staff, so the
    action that triggered it (like adding a volunteer) still succeeds.
    """
    ctx = {"shelter": shelter_details(), "site_url": settings.SITE_URL, **context}
    subject = " ".join(render_to_string(f"emails/{template_key}_subject.txt", ctx).split())
    text = render_to_string(f"emails/{template_key}.txt", ctx)
    html = render_to_string(f"emails/{template_key}.html", ctx)
    log = EmailLog.objects.create(
        to=to, template_key=template_key, subject=subject, related_user=related_user
    )
    try:
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
        message.attach_alternative(html, "text/html")
        message.send()
    except Exception as exc:  # SMTP failures come in many types; none may break the page.
        logger.exception(
            "Email %s to user %s failed", template_key, getattr(related_user, "pk", "-")
        )
        log.error = f"{type(exc).__name__}: {exc}"[:300]
        log.save(update_fields=["error"])
        return log
    log.sent_at = timezone.now()
    log.save(update_fields=["sent_at"])
    return log
