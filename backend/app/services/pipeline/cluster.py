"""Cluster matched documents into security events.

Deterministic event id keyed on ``(canonical_dep, day_bucket)`` so repeat
runs converge on the same ``security_events`` row. Within a day bucket, all
matches for the same dependency merge into a single event — fine for V1
demo signal density.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _canonical(watch_item: dict[str, Any]) -> str:
    return f"{watch_item.get('ecosystem', 'software')}:{watch_item.get('name', '')}".lower()


def _event_id(canonical: str, day: str) -> str:
    digest = hashlib.sha256(f"{canonical}|{day}".encode()).hexdigest()
    return "se_" + digest[:24]


def _today() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def cluster_into_events(
    candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Returns a list of cluster dicts ready to score.

    Cluster shape::

        {
            "event_id": str,
            "canonical_dep": str,
            "day": str,
            "title": str,
            "summary": str,
            "signals": [(doc_record, family, weight)],
            "matches": [(watch_item_id, score, reason)],
            "doc_titles": [str, ...],
        }
    """

    if not candidates:
        return []

    day = _today()
    buckets: dict[str, dict[str, Any]] = {}

    for cand in candidates:
        watch = cand["watch_item"]
        doc = cand["doc"]
        canonical = _canonical(watch)
        ev_id = _event_id(canonical, day)

        meta = doc.get("meta") or {}
        title = meta.get("title") or doc.get("publisher") or "Security finding"
        family = meta.get("family") or "unknown"
        weight = int(meta.get("weight") or 0)

        bucket = buckets.setdefault(
            ev_id,
            {
                "event_id": ev_id,
                "canonical_dep": canonical,
                "day": day,
                "title": "",
                "summary": "",
                "signals": [],
                "matches": [],
                "doc_titles": [],
                "_seen_doc_ids": set(),
                "_seen_match_keys": set(),
            },
        )

        if doc["id"] not in bucket["_seen_doc_ids"]:
            bucket["_seen_doc_ids"].add(doc["id"])
            bucket["signals"].append((doc, family, weight))
            bucket["doc_titles"].append(title)

        match_key = (watch["id"], doc["id"])
        if match_key not in bucket["_seen_match_keys"]:
            bucket["_seen_match_keys"].add(match_key)
            bucket["matches"].append(
                {
                    "watch_item_id": watch["id"],
                    "user_id": watch.get("user_id"),
                    "doc_id": doc["id"],
                    "score": cand["score"],
                    "reason": cand["reason"],
                }
            )

    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        bucket["title"] = _pick_title(bucket["doc_titles"], bucket["canonical_dep"])
        bucket["summary"] = _build_summary(bucket["signals"])
        bucket.pop("_seen_doc_ids", None)
        bucket.pop("_seen_match_keys", None)
        out.append(bucket)

    log.info("cluster %d event(s) from %d candidate(s)", len(out), len(candidates))
    return out


def _pick_title(titles: list[str], canonical: str) -> str:
    titles = [t for t in titles if t]
    if not titles:
        return f"Security signal for {canonical}"
    titles.sort(key=len, reverse=True)
    return titles[0][:200]


def _build_summary(signals: list[tuple[dict[str, Any], str, int]]) -> str:
    parts: list[str] = []
    for doc, family, _weight in signals[:5]:
        text = (doc.get("text") or "").strip().splitlines()
        first_line = next((line for line in text if line.strip()), "")
        if first_line:
            parts.append(f"[{family}] {first_line[:280]}")
    return "\n".join(parts)
