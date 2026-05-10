"""Severity + confidence scoring (PRD §13)."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


_IMPACT_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bRCE\b|remote\s+code\s+execution", re.IGNORECASE), 40),
    (re.compile(r"\bauth(entication)?\s+bypass", re.IGNORECASE), 30),
    (re.compile(r"credential\s+(leak|exposure|theft)", re.IGNORECASE), 30),
    (re.compile(r"supply[-\s]?chain", re.IGNORECASE), 25),
    (re.compile(r"\bzero[-\s]?day\b", re.IGNORECASE), 25),
    (re.compile(r"\bsql\s*injection\b", re.IGNORECASE), 18),
    (re.compile(r"\bxss\b|cross[-\s]?site\s+scripting", re.IGNORECASE), 12),
    (re.compile(r"denial\s+of\s+service|\bDoS\b|\bDDoS\b", re.IGNORECASE), 10),
    (re.compile(r"path\s+traversal|directory\s+traversal", re.IGNORECASE), 12),
    (re.compile(r"privilege\s+escalation", re.IGNORECASE), 18),
]
_CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
_CRITICAL_LABEL = re.compile(r"\bcritical\b", re.IGNORECASE)
_HIGH_LABEL = re.compile(r"\bhigh\s+severity\b|severity[:\s]+high", re.IGNORECASE)


def score_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        body = _event_text(event)
        severity = _severity(body)
        confidence = _confidence(event)
        scored = {
            **event,
            "severity": severity,
            "confidence": confidence,
            "tier": _tier(severity),
        }
        out.append(scored)
    log.info(
        "score: %s",
        ", ".join(
            f"{e['canonical_dep']}={e['severity']}/{e['confidence']}" for e in out
        ),
    )
    return out


def _event_text(event: dict[str, Any]) -> str:
    parts: list[str] = [event.get("title", ""), event.get("summary", "")]
    for doc, _family, _weight in event.get("signals", []):
        parts.append(doc.get("text") or "")
    return "\n".join(p for p in parts if p)


def _severity(text: str) -> int:
    score = 30
    for pattern, bump in _IMPACT_PATTERNS:
        if pattern.search(text):
            score += bump
            if score >= 100:
                break
    if _CVE_PATTERN.search(text):
        score += 15
    if _CRITICAL_LABEL.search(text):
        score = max(score, 80)
    elif _HIGH_LABEL.search(text):
        score = max(score, 65)
    return max(0, min(100, score))


def _confidence(event: dict[str, Any]) -> int:
    signals: list[tuple[Any, str, int]] = event.get("signals", []) or []
    if not signals:
        return 0
    distinct_families = {family for _doc, family, _w in signals}
    base = max(weight for _doc, _family, weight in signals)
    score = min(100, base + 5 * (len(distinct_families) - 1))
    if any(family == "structured_intel" for _doc, family, _w in signals):
        score = min(100, score + 5)
    return score


def _tier(severity: int) -> str:
    if severity >= 80:
        return "critical"
    if severity >= 60:
        return "high"
    if severity >= 35:
        return "medium"
    return "low"


def should_alert(event: dict[str, Any]) -> bool:
    sev = event.get("severity", 0)
    conf = event.get("confidence", 0)
    if sev >= 80 and conf >= 70:
        return True
    if sev >= 60 and conf >= 75:
        return True
    return False
