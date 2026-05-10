"""Gemini-backed second-opinion judge.

Sits between :func:`score_events` and :func:`dispatch_alerts`. For every
event that clears the cheap deterministic prefilter, we ask Gemini to:

1. **Classify intent** — is this an actual security incident affecting
   the dep, or is it a tutorial / news / unrelated mention that the
   regex severity-scorer was tricked by?
2. **Adjust severity / confidence** — within bounded ranges so an LLM
   hallucination can't single-handedly flip a critical event into a
   low one.
3. **Write a 2–3 sentence summary** the alert email will surface.

Failure modes (no API key, HTTP error, malformed JSON, rate-limit)
degrade gracefully to deterministic-only scoring with a warning. The
deterministic spine remains the source of truth — Gemini is a filter,
not a replacement.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...config import get_settings
from .. import gemini

log = logging.getLogger(__name__)


# Hard-bound LLM influence so a confused model can't swing severity wildly.
_MAX_SEV_ADJUSTMENT = 30
_INTENT_VALUES = {"advisory", "incident", "news", "tutorial", "discussion", "unrelated"}
# Intents Gemini may return that we treat as "this isn't a real
# vulnerability for *this* dep" — alerts get suppressed regardless of
# severity.
_NON_VULNERABILITY_INTENTS = {"tutorial", "discussion", "unrelated"}


async def judge_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate scored events with Gemini's verdict, in place.

    Returns the same list (also mutated). Each event gains the keys:
    ``llm_intent``, ``llm_summary``, ``llm_severity_adjustment``,
    ``llm_confidence``, ``llm_status`` (one of ``ok`` / ``skipped`` /
    ``error``), and an updated ``severity`` / ``confidence`` /
    ``suppressed`` field. ``suppressed=True`` means dispatch_alerts must
    skip this event even if :func:`should_alert` would otherwise fire.
    """

    if not events:
        return events
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        for ev in events:
            ev["llm_status"] = "skipped"
        return events

    budget = settings.MAX_GEMINI_CALLS_PER_RUN
    threshold = settings.GEMINI_PREFILTER_MIN_SEVERITY
    calls = 0

    # Sort highest-severity first so when the budget is tight we spend it
    # on the events most likely to matter.
    ranked = sorted(
        enumerate(events),
        key=lambda pair: pair[1].get("severity", 0),
        reverse=True,
    )

    for _idx, ev in ranked:
        if ev.get("severity", 0) < threshold:
            ev["llm_status"] = "skipped"
            continue
        if calls >= budget:
            ev["llm_status"] = "skipped"
            continue
        try:
            verdict = await _judge_one(ev)
        except Exception as err:  # noqa: BLE001 — log + continue
            log.warning(
                "judge: gemini call failed event=%s: %s", ev.get("event_id"), err
            )
            ev["llm_status"] = "error"
            continue
        calls += 1
        _apply(ev, verdict)

    log.info("judge: gemini calls=%d budget=%d events=%d", calls, budget, len(events))
    return events


async def _judge_one(event: dict[str, Any]) -> dict[str, Any]:
    prompt = _build_prompt(event)
    return await gemini.generate_json(prompt)


def _build_prompt(event: dict[str, Any]) -> str:
    canonical = event.get("canonical_dep", "")
    title = event.get("title", "")
    sev = event.get("severity", 0)
    conf = event.get("confidence", 0)
    tier = event.get("tier", "low")

    snippets: list[str] = []
    for i, (doc, family, _weight) in enumerate(event.get("signals", [])[:3], start=1):
        text = (doc.get("text") or "").strip().replace("\r", "")
        snippets.append(
            f"[{i}] family={family} publisher={doc.get('publisher','')}\n"
            f"url={doc.get('url','')}\n"
            f"text: {text[:800]}"
        )
    sources_block = "\n\n".join(snippets) or "(no source snippets)"

    return (
        "You are a security signal classifier for a vulnerability monitoring "
        "tool. A deterministic regex pipeline has flagged the following event "
        "and assigned an initial severity/confidence. Your job is to (a) decide "
        "whether this is actually a security issue affecting the named "
        "dependency, and (b) write a tight 2-3 sentence email-ready summary.\n\n"
        f"Dependency under watch: {canonical}\n"
        f"Event title           : {title}\n"
        f"Initial severity      : {sev}/100 (tier: {tier})\n"
        f"Initial confidence    : {conf}/100\n\n"
        f"Source material:\n{sources_block}\n\n"
        "Respond with a single JSON object and NOTHING else. Schema:\n"
        "{\n"
        '  "is_vulnerability": boolean,    // true iff this describes a real security issue (advisory, breach, exploit) actually affecting the named dep. False if the dep is mentioned in a tutorial, generic news, casual discussion, or about a different package.\n'
        '  "intent": "advisory" | "incident" | "news" | "tutorial" | "discussion" | "unrelated",\n'
        '  "severity_adjustment": integer between -30 and 30,  // negative if the deterministic score overstates the severity, positive if it understates it.\n'
        '  "confidence": integer 0-100,    // your confidence the finding is real and material to a user pinning this dep.\n'
        '  "summary": "2-3 plain-English sentences explaining WHY this is (or is not) a security issue, citing impact and affected versions if known. Suitable for an alert email body."\n'
        "}\n"
    )


def _apply(event: dict[str, Any], verdict: dict[str, Any]) -> None:
    intent_raw = str(verdict.get("intent") or "").lower().strip()
    intent = intent_raw if intent_raw in _INTENT_VALUES else "unrelated"
    is_vuln = bool(verdict.get("is_vulnerability"))
    sev_adj = _coerce_int(verdict.get("severity_adjustment"), 0)
    sev_adj = max(-_MAX_SEV_ADJUSTMENT, min(_MAX_SEV_ADJUSTMENT, sev_adj))
    llm_conf = _coerce_int(verdict.get("confidence"), event.get("confidence", 0))
    llm_conf = max(0, min(100, llm_conf))
    summary = str(verdict.get("summary") or "").strip()

    event["llm_status"] = "ok"
    event["llm_intent"] = intent
    event["llm_severity_adjustment"] = sev_adj
    event["llm_confidence"] = llm_conf
    event["llm_summary"] = summary
    event["llm_is_vulnerability"] = is_vuln

    base_sev = int(event.get("severity") or 0)
    new_sev = max(0, min(100, base_sev + sev_adj))
    event["severity"] = new_sev
    event["tier"] = _tier(new_sev)

    # Blend: prefer Gemini's confidence but anchor to deterministic so a
    # single LLM call can't unilaterally fail-open. Average, weight 60/40
    # toward the LLM (it has seen the actual text).
    base_conf = int(event.get("confidence") or 0)
    blended = round(0.4 * base_conf + 0.6 * llm_conf)
    event["confidence"] = max(0, min(100, blended))

    # Suppression: if Gemini explicitly says it's not a vulnerability, OR
    # the intent is in our non-vuln set, suppress the alert.
    event["suppressed"] = (not is_vuln) or (intent in _NON_VULNERABILITY_INTENTS)


def _coerce_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _tier(severity: int) -> str:
    if severity >= 80:
        return "critical"
    if severity >= 60:
        return "high"
    if severity >= 35:
        return "medium"
    return "low"


# Re-exported for tests / callers that want to peek at the prompt.
__all__ = ["judge_events", "_build_prompt", "_apply"]


# json_module re-export so tests can monkeypatch easily without touching
# the gemini service directly. Internal-only.
_ = json  # noqa: F841 — keep the import resolvable for tests
