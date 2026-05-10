"""Email sender — dry-run + SendGrid + Gmail SMTP transports."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from app.services.email_sender import EmailMessage, send_email


def _reset_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()


def _clear_email_env(monkeypatch):
    """Empty every email-related env var so .env file values don't leak.

    pydantic-settings reads .env *and* os.environ. Using ``delenv`` only
    drops the latter; the .env file values still come through. Setting
    them to empty strings via ``setenv`` overrides the .env entry."""

    for var in (
        "SENDGRID_API_KEY",
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "EMAIL_FROM",
    ):
        monkeypatch.setenv(var, "")


# ---------- dry-run ------------------------------------------------------


def test_dry_run_returns_dry_run_state(caplog):
    caplog.set_level(logging.INFO, logger="app.services.email_sender")
    out = send_email(EmailMessage(to="x@y.com", subject="hi", body="body"))
    assert out == "dry_run"
    assert any("EMAIL DRY-RUN" in rec.getMessage() for rec in caplog.records)


def test_no_dry_run_without_credentials_returns_failed(monkeypatch):
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    _clear_email_env(monkeypatch)
    _reset_settings_cache()
    out = send_email(EmailMessage(to="x@y.com", subject="hi", body="body"))
    assert out == "failed"


# ---------- SendGrid -----------------------------------------------------


@pytest.fixture
def sendgrid_env(monkeypatch):
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-key")
    monkeypatch.setenv("EMAIL_FROM", "alerts@example.com")
    _reset_settings_cache()
    yield
    _reset_settings_cache()


def test_sendgrid_202_returns_sent(sendgrid_env):
    with respx.mock(base_url="https://api.sendgrid.com") as router:
        route = router.post("/v3/mail/send").mock(
            return_value=httpx.Response(202, text="")
        )
        out = send_email(
            EmailMessage(to="ash@example.com", subject="[CRITICAL] django", body="…")
        )
        assert out == "sent"
        assert route.call_count == 1
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer SG.test-key"
        body = request.read().decode("utf-8")
        assert "ash@example.com" in body
        assert "alerts@example.com" in body
        assert "[CRITICAL] django" in body


def test_sendgrid_4xx_returns_failed(sendgrid_env, caplog):
    caplog.set_level(logging.ERROR, logger="app.services.email_sender")
    with respx.mock(base_url="https://api.sendgrid.com") as router:
        router.post("/v3/mail/send").mock(
            return_value=httpx.Response(
                401, json={"errors": [{"message": "bad key"}]}
            )
        )
        out = send_email(
            EmailMessage(to="ash@example.com", subject="x", body="y")
        )
        assert out == "failed"
        assert any("sendgrid rejected" in r.getMessage() for r in caplog.records)


def test_sendgrid_network_error_returns_failed(sendgrid_env):
    with respx.mock(base_url="https://api.sendgrid.com") as router:
        router.post("/v3/mail/send").mock(
            side_effect=httpx.ConnectError("dns broke")
        )
        out = send_email(
            EmailMessage(to="ash@example.com", subject="x", body="y")
        )
        assert out == "failed"


def test_sendgrid_without_from_address_fails_fast(monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-key")
    _reset_settings_cache()
    caplog.set_level(logging.ERROR, logger="app.services.email_sender")
    out = send_email(EmailMessage(to="x@y.com", subject="x", body="y"))
    _reset_settings_cache()
    assert out == "failed"
    assert any("EMAIL_FROM" in r.getMessage() for r in caplog.records)


def test_sendgrid_takes_precedence_over_gmail(monkeypatch):
    """If both SendGrid and Gmail SMTP are configured, SendGrid wins —
    we never want to attempt SMTP on a host that may block port 465."""
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-key")
    monkeypatch.setenv("EMAIL_FROM", "alerts@example.com")
    monkeypatch.setenv("GMAIL_USER", "fallback@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "wouldnt work")
    _reset_settings_cache()
    try:
        with respx.mock(base_url="https://api.sendgrid.com") as router:
            router.post("/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            out = send_email(
                EmailMessage(to="x@y.com", subject="x", body="y")
            )
            assert out == "sent"
    finally:
        _reset_settings_cache()
