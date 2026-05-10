"""Email sender — dry-run logging path."""

from __future__ import annotations

import logging

from app.services.email_sender import EmailMessage, send_email


def test_dry_run_returns_dry_run_state(caplog):
    caplog.set_level(logging.INFO, logger="app.services.email_sender")
    out = send_email(EmailMessage(to="x@y.com", subject="hi", body="body"))
    assert out == "dry_run"
    assert any("EMAIL DRY-RUN" in rec.getMessage() for rec in caplog.records)


def test_no_dry_run_without_credentials_returns_failed(monkeypatch):
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    out = send_email(EmailMessage(to="x@y.com", subject="hi", body="body"))
    assert out == "failed"
