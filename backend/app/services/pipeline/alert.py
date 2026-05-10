"""Alert dispatch — turn scored events into emails (or dry-run logs)."""

from __future__ import annotations

import logging
from typing import Any

from ...store.json_store import JsonStore
from ..email_sender import EmailMessage, send_email

log = logging.getLogger(__name__)


def render_alert(user: dict[str, Any], event: dict[str, Any]) -> EmailMessage:
    canonical = event.get("canonical_dep", "")
    tier = (event.get("tier") or "low").upper()
    title = event.get("title", "Security finding")
    subject = f"[{tier}] {canonical} — {title[:120]}"

    sources = []
    for doc, family, weight in (event.get("signals") or [])[:3]:
        url = doc.get("url") or ""
        publisher = doc.get("publisher") or family
        sources.append(f"- [{publisher}] {url}".rstrip(" "))

    # Prefer the Gemini-generated summary (2-3 plain-English sentences,
    # email-ready) and fall back to the deterministic cluster summary
    # (raw doc-line dump) only when the judge wasn't run.
    llm_summary = (event.get("llm_summary") or "").strip()
    summary = llm_summary or event.get("summary") or "(no summary)"
    intent = event.get("llm_intent") or ""
    intent_line = f"AI intent           : {intent}\n" if intent else ""

    body = (
        f"Security Alerts Copilot\n"
        f"========================\n\n"
        f"Affected dependency : {canonical}\n"
        f"Severity            : {event.get('severity')} ({tier})\n"
        f"Confidence          : {event.get('confidence')}\n"
        + intent_line
        + f"Title               : {title}\n\n"
        f"Summary\n-------\n{summary}\n\n"
        f"Top sources\n-----------\n" + ("\n".join(sources) or "- (none)") + "\n\n"
        f"Suggested next step\n-------------------\n"
        f"Verify the advisory, check your installed version, and apply the upstream fix or temporary mitigation.\n"
    )
    return EmailMessage(to=user["email"], subject=subject, body=body)


def dispatch_alerts(
    store: JsonStore,
    user: dict[str, Any],
    scored_events: list[dict[str, Any]],
    *,
    should_alert,
) -> int:
    sent = 0
    for event in scored_events:
        store.events.upsert(
            {
                "id": event["event_id"],
                "title": event["title"],
                "summary": event["summary"],
                "severity": event["severity"],
                "confidence": event["confidence"],
                "canonical_dep": event["canonical_dep"],
                "status": event.get("status", "rumor"),
            }
        )
        store.event_signals.append_many(
            {
                "event_id": event["event_id"],
                "source_document_id": doc["id"],
                "family": family,
                "weight": weight,
            }
            for doc, family, weight in event.get("signals", [])
        )
        store.relevance_matches.append_many(
            {
                "event_id": event["event_id"],
                "watch_item_id": match["watch_item_id"],
                "score": match["score"],
                "reason": match["reason"],
            }
            for match in event.get("matches", [])
        )

        if event.get("suppressed"):
            log.info(
                "alert suppressed by judge user=%s event=%s intent=%s",
                user["id"],
                event["event_id"],
                event.get("llm_intent"),
            )
            continue
        if not should_alert(event):
            continue
        if store.alerts.has_for(user["id"], event["event_id"]):
            log.debug(
                "alert dedupe user=%s event=%s", user["id"], event["event_id"]
            )
            continue

        message = render_alert(user, event)
        record = store.alerts.insert(
            {
                "user_id": user["id"],
                "event_id": event["event_id"],
                "severity": event["severity"],
                "confidence": event["confidence"],
                "channel": "email",
                "state": "queued",
                "payload": {"subject": message.subject, "body": message.body},
            }
        )
        outcome = send_email(message)
        store.alerts.update_state(record["id"], outcome)
        sent += 1
    return sent
