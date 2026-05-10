"""Send a single hardcoded email to verify the SendGrid path end-to-end.

Bypasses the pipeline entirely so we can tell a credentials / network bug
apart from a "pipeline produced nothing to alert on" no-op.

Usage:
    python scripts/send_test_email.py [recipient]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.email_sender import EmailMessage, send_email


def main(recipient: str | None) -> None:
    settings = get_settings()
    target = recipient or settings.EMAIL_FROM
    if not target:
        raise SystemExit("no recipient (pass arg or set EMAIL_FROM in .env)")

    message = EmailMessage(
        to=target,
        subject="[TEST] Security Alerts Copilot — SendGrid smoke test",
        body=(
            "This is a one-off SendGrid smoke test from scripts/send_test_email.py.\n\n"
            "If you can read this, SENDGRID_API_KEY + EMAIL_FROM + "
            "EMAIL_DRY_RUN=false are wired correctly. The hourly pipeline will "
            "use this same channel for real CRITICAL/HIGH alerts on your "
            "dependency watchlist.\n"
        ),
    )
    print(f"sending dry_run={settings.EMAIL_DRY_RUN} to={target} ...")
    outcome = send_email(message)
    print(f"outcome: {outcome}")
    if outcome == "failed":
        raise SystemExit(2)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
