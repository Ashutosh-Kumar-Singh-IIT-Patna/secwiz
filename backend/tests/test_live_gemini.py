"""Live Gemini tests — auto-skip when ``GEMINI_API_KEY`` is missing.

Each test is marked ``live_gemini``; the marker is filtered in
``conftest.pytest_collection_modifyitems`` when no key is present, so a
no-key run still passes cleanly. With a key present these run inline and
burn a tiny amount of free-tier credit per session.
"""

from __future__ import annotations

import pytest

from app.services import gemini
from app.services.pipeline.judge import judge_events


pytestmark = pytest.mark.live_gemini


async def test_live_gemini_returns_valid_json():
    """Sanity check: ``generate_json`` actually round-trips a JSON object."""

    result = await gemini.generate_json(
        'Return the JSON object: {"ok": true, "n": 7}. No prose, just the JSON.'
    )
    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("n") == 7


async def test_live_gemini_judges_a_real_advisory():
    """End-to-end judge against a hand-built event mimicking real OSV output."""

    osv_text = (
        "Affected package: lodash (npm). Versions < 4.17.21 are vulnerable to "
        "prototype pollution leading to remote code execution. CVE-2021-23337. "
        "Severity: High. Upgrade to 4.17.21 or later."
    )
    event = {
        "event_id": "se_live",
        "canonical_dep": "npm:lodash",
        "title": "Prototype pollution in lodash",
        "summary": osv_text,
        "severity": 75,
        "confidence": 90,
        "tier": "high",
        "signals": [
            (
                {
                    "id": "sd_1",
                    "url": "https://osv.dev/vulnerability/CVE-2021-23337",
                    "publisher": "OSV",
                    "text": osv_text,
                },
                "structured_intel",
                90,
            )
        ],
        "matches": [],
    }
    out = await judge_events([event])
    judged = out[0]
    assert judged["llm_status"] == "ok"
    assert judged["llm_is_vulnerability"] is True
    assert judged["llm_intent"] in {"advisory", "incident"}
    assert judged["suppressed"] is False
    # Expect a useful sentence-level summary.
    assert isinstance(judged["llm_summary"], str)
    assert len(judged["llm_summary"]) > 30


async def test_live_gemini_suppresses_a_tutorial():
    """Gemini should classify a generic blog post as tutorial/discussion
    and flip ``suppressed=True`` even though the deterministic regex
    found CVE/RCE keywords."""

    blog_text = (
        "In this tutorial we'll explore why prototype-pollution-style RCE "
        "issues like CVE-2021-23337 happen. We'll write our own toy library "
        "(not lodash, just a teaching example) and see how to defend "
        "against the pattern. No actual vulnerability is being disclosed."
    )
    event = {
        "event_id": "se_live_tut",
        "canonical_dep": "npm:lodash",
        "title": "Understanding prototype pollution RCEs",
        "summary": blog_text,
        "severity": 85,  # deterministic was tricked by RCE+CVE keywords
        "confidence": 60,
        "tier": "critical",
        "signals": [
            (
                {
                    "id": "sd_t",
                    "url": "https://blog.example.com/proto-rce-tutorial",
                    "publisher": "example.com",
                    "text": blog_text,
                },
                "url_scraper",
                40,
            )
        ],
        "matches": [],
    }
    out = await judge_events([event])
    judged = out[0]
    assert judged["llm_status"] == "ok"
    # The judge should NOT flag this as a real vuln affecting lodash.
    assert judged["llm_is_vulnerability"] is False or judged["suppressed"] is True
