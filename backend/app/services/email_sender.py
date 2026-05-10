"""Email sender — SendGrid Web API only (HTTPS:443).

Two modes, picked at runtime:

1. ``EMAIL_DRY_RUN=true`` (default for demos) — log the rendered subject +
   body and return ``"dry_run"``. No network calls.
2. ``SENDGRID_API_KEY`` set — POST to SendGrid's Web API. Required on
   hosts that block outbound SMTP (Render free, Heroku, Vercel, Fly.io
   free) and works everywhere else too.

The earlier Gmail SMTP path was removed because every cloud free tier we
might deploy on blocks port 25/465/587. Single transport keeps the
config surface small and the failure modes one-dimensional.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


def send_email(message: EmailMessage) -> str:
    """Return the post-send state to write into ``alerts.state``.

    Possible return values: ``"dry_run"``, ``"sent"``, ``"failed"``.
    """

    settings = get_settings()

    if settings.EMAIL_DRY_RUN:
        log.info(
            "EMAIL DRY-RUN to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.body,
        )
        return "dry_run"

    if not settings.SENDGRID_API_KEY:
        log.error(
            "EMAIL_DRY_RUN=false but SENDGRID_API_KEY is empty; cannot send"
        )
        return "failed"

    return _send_via_sendgrid(message, settings)


def _send_via_sendgrid(message: EmailMessage, settings) -> str:
    sender = settings.EMAIL_FROM
    if not sender:
        log.error(
            "SendGrid requires EMAIL_FROM (the verified Single Sender / "
            "domain identity); cannot send"
        )
        return "failed"

    payload = {
        "personalizations": [
            {
                "to": [{"email": message.to}],
                "subject": message.subject,
            }
        ],
        "from": {"email": sender},
        "content": [{"type": "text/plain", "value": message.body}],
    }
    headers = {
        "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{settings.SENDGRID_API_BASE.rstrip('/')}/mail/send"

    try:
        # SendGrid timeouts on the public API are ~10s in practice;
        # ``HTTP_TIMEOUT_SECONDS`` (30 by default) is plenty.
        with httpx.Client(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as err:
        log.exception("sendgrid request failed: %s", err)
        return "failed"

    # SendGrid returns 202 for accepted-for-delivery. 4xx/5xx carry a
    # JSON ``errors`` array we can surface for debugging.
    if 200 <= response.status_code < 300:
        log.info(
            "email sent via sendgrid to=%s subject=%s status=%s",
            message.to,
            message.subject,
            response.status_code,
        )
        return "sent"

    body_excerpt = (response.text or "")[:500]
    log.error(
        "sendgrid rejected send to=%s status=%s body=%s",
        message.to,
        response.status_code,
        body_excerpt,
    )
    return "failed"
