"""Gemini judge unit tests.

Exercises the pipeline layer (`judge_events`) by mocking the underlying
``gemini.generate_json`` call. A single live test (no key required to
collect) lives in ``test_live_anakin.py``-style sibling — see
``test_live_gemini.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.services import gemini
from app.services.pipeline import judge as judge_module
from app.services.pipeline.judge import judge_events


# ---------- gemini.generate_json (mocked HTTP) ---------------------------


_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-flash-latest:generateContent"
)


@respx.mock
async def test_gemini_generate_json_parses_text_part(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx.post(_GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"is_vulnerability": True, "summary": "ok"})}
                            ]
                        }
                    }
                ]
            },
        )
    )
    result = await gemini.generate_json("test prompt")
    assert route.called
    assert result == {"is_vulnerability": True, "summary": "ok"}
    sent = route.calls.last.request
    assert sent.headers["X-goog-api-key"] == "test-key"
    # And NOT in the URL — header auth keeps it out of URL logs.
    assert "key=" not in str(sent.url)


@respx.mock
async def test_gemini_generate_json_raises_on_4xx(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    respx.post(_GEMINI_URL).mock(
        return_value=httpx.Response(429, json={"error": "rate limit"})
    )

    with pytest.raises(gemini.GeminiError) as err:
        await gemini.generate_json("p")
    assert err.value.status == 429


@respx.mock
async def test_gemini_generate_json_rejects_non_json_body(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    respx.post(_GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "this is not json"}]}}
                ]
            },
        )
    )
    with pytest.raises(ValueError):
        await gemini.generate_json("p")


async def test_gemini_generate_json_no_key_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    with pytest.raises(gemini.GeminiError):
        await gemini.generate_json("p")


# ---------- judge_events --------------------------------------------------


def _event(severity: int = 75, **kwargs) -> dict:
    base = {
        "event_id": "se_abc",
        "canonical_dep": "npm:lodash",
        "title": "RCE in lodash",
        "summary": "(legacy summary)",
        "severity": severity,
        "confidence": 80,
        "tier": "high",
        "signals": [
            (
                {"id": "sd_1", "url": "https://x", "publisher": "OSV", "text": "RCE"},
                "structured_intel",
                90,
            )
        ],
        "matches": [],
    }
    base.update(kwargs)
    return base


async def test_judge_skips_when_no_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    events = [_event()]
    out = await judge_events(events)
    assert out[0]["llm_status"] == "skipped"
    assert "llm_summary" not in out[0]
    assert "suppressed" not in out[0]


async def test_judge_skips_below_prefilter(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_PREFILTER_MIN_SEVERITY", "50")
    from app.config import get_settings

    get_settings.cache_clear()

    called = []

    async def fake_generate_json(prompt, **kw):
        called.append(prompt)
        return {"is_vulnerability": True, "intent": "advisory", "severity_adjustment": 0,
                "confidence": 90, "summary": "x"}

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake_generate_json)

    events = [_event(severity=20), _event(severity=80)]
    out = await judge_events(events)
    assert out[0]["llm_status"] == "skipped"
    assert out[1]["llm_status"] == "ok"
    assert len(called) == 1


async def test_judge_suppresses_when_intent_is_tutorial(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.config import get_settings

    get_settings.cache_clear()

    async def fake(prompt, **kw):
        return {
            "is_vulnerability": False,
            "intent": "tutorial",
            "severity_adjustment": -25,
            "confidence": 30,
            "summary": "Just a blog post about lodash patterns, not an actual vuln.",
        }

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake)

    events = [_event(severity=85, confidence=80)]
    out = await judge_events(events)
    ev = out[0]
    assert ev["suppressed"] is True
    assert ev["llm_intent"] == "tutorial"
    assert ev["llm_summary"].startswith("Just a blog post")
    assert ev["severity"] == 85 - 25  # adjustment applied
    assert ev["tier"] == "high"


async def test_judge_alert_dispatch_skips_suppressed(monkeypatch, store, make_user):
    """Suppressed events must not trigger an email even when
    `should_alert` would otherwise return True."""

    from app.services.pipeline.alert import dispatch_alerts

    user = make_user("a@b.c")
    suppressed_ev = _event(severity=85, confidence=85)
    suppressed_ev["suppressed"] = True
    suppressed_ev["llm_intent"] = "tutorial"

    sent = dispatch_alerts(
        store, user, [suppressed_ev], should_alert=lambda _ev: True
    )
    assert sent == 0
    # Event itself still gets persisted (we want history of suppressed signals).
    persisted_ids = {ev["id"] for ev in store.events.all()}
    assert suppressed_ev["event_id"] in persisted_ids
    assert store.alerts.has_for(user["id"], suppressed_ev["event_id"]) is False


async def test_judge_severity_bump_can_promote_tier(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.config import get_settings

    get_settings.cache_clear()

    async def fake(prompt, **kw):
        return {
            "is_vulnerability": True,
            "intent": "advisory",
            "severity_adjustment": 25,
            "confidence": 95,
            "summary": "Confirmed RCE in lodash <4.17.21 via prototype pollution chain.",
        }

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake)

    events = [_event(severity=60, confidence=70)]
    out = await judge_events(events)
    assert out[0]["severity"] == 85
    assert out[0]["tier"] == "critical"
    assert out[0]["suppressed"] is False
    # Confidence is blended 40% deterministic + 60% llm: round(0.4*70 + 0.6*95) = 85
    assert out[0]["confidence"] == 85


async def test_judge_severity_adjustment_clamped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.config import get_settings

    get_settings.cache_clear()

    async def fake(prompt, **kw):
        return {
            "is_vulnerability": True,
            "intent": "advisory",
            "severity_adjustment": 999,  # absurd
            "confidence": 200,  # absurd
            "summary": "ok",
        }

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake)

    events = [_event(severity=70, confidence=70)]
    out = await judge_events(events)
    assert out[0]["llm_severity_adjustment"] == 30  # clamped to MAX_SEV_ADJUSTMENT
    assert out[0]["severity"] == 100  # clamped to ceiling
    assert out[0]["llm_confidence"] == 100  # clamped to ceiling


async def test_judge_gemini_error_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from app.config import get_settings

    get_settings.cache_clear()

    async def fake(prompt, **kw):
        raise gemini.GeminiError(500, "boom")

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake)

    events = [_event(severity=85, confidence=80)]
    out = await judge_events(events)
    assert out[0]["llm_status"] == "error"
    # No suppression, no severity change.
    assert out[0]["severity"] == 85
    assert out[0]["confidence"] == 80
    assert "suppressed" not in out[0] or out[0]["suppressed"] is False


async def test_judge_respects_call_budget(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAX_GEMINI_CALLS_PER_RUN", "1")
    from app.config import get_settings

    get_settings.cache_clear()

    calls = []

    async def fake(prompt, **kw):
        calls.append(1)
        return {"is_vulnerability": True, "intent": "advisory", "severity_adjustment": 0,
                "confidence": 80, "summary": "x"}

    monkeypatch.setattr(judge_module.gemini, "generate_json", fake)

    events = [_event(severity=90), _event(severity=70), _event(severity=60)]
    out = await judge_events(events)
    assert len(calls) == 1
    # Budget should spend on the highest-severity event first.
    judged_severities = [ev["severity"] for ev in out if ev["llm_status"] == "ok"]
    skipped_severities = [ev["severity"] for ev in out if ev["llm_status"] == "skipped"]
    assert max(judged_severities) == 90
    assert sorted(skipped_severities) == [60, 70]


# ---------- alert email surface ------------------------------------------


def test_render_alert_uses_llm_summary_when_present():
    from app.services.pipeline.alert import render_alert

    user = {"id": "u_x", "email": "user@example.com"}
    event = {
        "canonical_dep": "npm:lodash",
        "tier": "critical",
        "severity": 90,
        "confidence": 85,
        "title": "RCE in lodash",
        "summary": "(legacy doc dump)",
        "llm_summary": "lodash < 4.17.21 has a prototype-pollution RCE; upgrade or pin to a patched release.",
        "llm_intent": "advisory",
        "signals": [
            ({"url": "https://osv.dev/x", "publisher": "OSV"}, "structured_intel", 90)
        ],
    }
    msg = render_alert(user, event)
    assert "prototype-pollution RCE" in msg.body
    assert "(legacy doc dump)" not in msg.body
    assert "AI intent           : advisory" in msg.body


def test_render_alert_falls_back_to_legacy_summary():
    from app.services.pipeline.alert import render_alert

    user = {"id": "u_x", "email": "user@example.com"}
    event = {
        "canonical_dep": "npm:lodash",
        "tier": "high",
        "severity": 70,
        "confidence": 75,
        "title": "Auth bypass discussion",
        "summary": "Heuristic-derived blurb",
        "signals": [],
    }
    msg = render_alert(user, event)
    assert "Heuristic-derived blurb" in msg.body
    assert "AI intent" not in msg.body
