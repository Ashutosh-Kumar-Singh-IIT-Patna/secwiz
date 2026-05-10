"""Email sender with three modes, picked at runtime by config:

1. ``EMAIL_DRY_RUN=true`` (default for demos) — log the rendered subject +
   body and return ``"dry_run"``. No network calls.
2. ``SENDGRID_API_KEY`` set — POST to SendGrid's Web API over HTTPS:443.
   Required on hosts that block outbound SMTP (Render free, Heroku,
   Vercel, Fly.io free).
3. ``GMAIL_USER`` + ``GMAIL_APP_PASSWORD`` set — Gmail SMTP_SSL on :465.
   Cheapest local path, but blocked by most cloud free tiers.

Order of precedence: dry-run > SendGrid > Gmail SMTP. The first one
configured wins, the rest are skipped silently. Return values feed
straight into ``alerts.state``.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as _StdlibEmailMessage

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

    if settings.SENDGRID_API_KEY:
        return _send_via_sendgrid(message, settings)

    if settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD:
        return _send_via_gmail_smtp(message, settings)

    log.error(
        "EMAIL_DRY_RUN=false but no transport configured "
        "(set SENDGRID_API_KEY or GMAIL_USER+GMAIL_APP_PASSWORD)"
    )
    return "failed"


# ---------- SendGrid Web API ---------------------------------------------


def _send_via_sendgrid(message: EmailMessage, settings) -> str:
    sender = settings.EMAIL_FROM or settings.GMAIL_USER
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


# ---------- Gmail SMTP (legacy / local) -----------------------------------


def _send_via_gmail_smtp(message: EmailMessage, settings) -> str:
    msg = _StdlibEmailMessage()
    msg["From"] = settings.EMAIL_FROM or settings.GMAIL_USER
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg.set_content(message.body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    except Exception as err:
        log.exception("smtp send failed: %s", err)
        return "failed"

    log.info(
        "email sent via gmail smtp to=%s subject=%s",
        message.to,
        message.subject,
    )
    return "sent"
