"""Gmail SMTP sender with a default-on dry-run path.

In dry-run mode (the default), :func:`send_email` writes the rendered
subject + body to logs and returns ``"dry_run"`` — handy for hackathon
demos without spamming a real inbox. Flip ``EMAIL_DRY_RUN=false`` in
``.env`` plus fill in ``GMAIL_USER`` / ``GMAIL_APP_PASSWORD`` to actually
send.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as _StdlibEmailMessage

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

    if not (settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD):
        log.error("EMAIL_DRY_RUN=false but GMAIL credentials are missing")
        return "failed"

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

    log.info("email sent to=%s subject=%s", message.to, message.subject)
    return "sent"
