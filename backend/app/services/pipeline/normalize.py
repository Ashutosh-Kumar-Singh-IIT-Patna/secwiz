"""Convert RawDoc dicts to persisted ``source_documents`` records.

Dedupe is content-hash-based over a sliding window (default 24 h, set via
``DEDUP_WINDOW_HOURS``): re-fetching the same OSV advisory hourly should
not produce 24 duplicate documents. Set ``DEDUP_WINDOW_HOURS=0`` to
disable dedup entirely (useful for demos where you want every run to
emit a fresh batch).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ...config import get_settings
from ...store.json_store import JsonStore

log = logging.getLogger(__name__)


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def normalize_docs(
    store: JsonStore, raw_docs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not raw_docs:
        return []

    window_hours = get_settings().DEDUP_WINDOW_HOURS
    dedup_enabled = window_hours > 0
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=window_hours)
    written: list[dict[str, Any]] = []
    seen_in_run: set[str] = set()

    for raw in raw_docs:
        text = raw.get("text") or ""
        if not text.strip():
            continue
        content_hash = _hash(text)
        if content_hash in seen_in_run:
            continue
        seen_in_run.add(content_hash)
        if dedup_enabled and store.source_documents.has_recent_hash(content_hash, cutoff):
            log.debug("dedupe skip hash=%s url=%s", content_hash, raw.get("url"))
            continue
        record = store.source_documents.insert(
            {
                "url": raw.get("url", ""),
                "publisher": raw.get("publisher", ""),
                "content_hash": content_hash,
                "text": text,
                "meta": {
                    "family": raw.get("family"),
                    "weight": raw.get("weight"),
                    "title": raw.get("title"),
                    "matched_dep_hint": raw.get("matched_dep_hint"),
                    **(raw.get("meta") or {}),
                },
            }
        )
        written.append(record)

    log.info(
        "normalize %d/%d docs persisted (rest deduped/empty)",
        len(written),
        len(raw_docs),
    )
    return written
