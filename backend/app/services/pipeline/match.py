"""Watchlist matching.

V1 stays deterministic: case-insensitive word-boundary regex on the watch
item ``name`` plus its declared aliases. Ecosystem hints (from the ingest
layer's ``matched_dep_hint``) raise the score when present.

Output: a list of ``Candidate`` dicts shaped::

    {
        "doc": <source_document record>,
        "watch_item": <watch_item record>,
        "score": int,
        "reason": str,
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def _compile_pattern(name: str, aliases: list[str]) -> re.Pattern[str]:
    parts = [re.escape(p) for p in [name, *aliases] if p]
    if not parts:
        return re.compile(r"$.^")  # never matches
    pattern = r"(?<![A-Za-z0-9_])(?:" + "|".join(parts) + r")(?![A-Za-z0-9_])"
    return re.compile(pattern, flags=re.IGNORECASE)


def _haystack(doc: dict[str, Any]) -> str:
    meta = doc.get("meta") or {}
    parts = [meta.get("title") or "", doc.get("text") or ""]
    return "\n".join(p for p in parts if p)


def match_to_watchlist(
    docs: list[dict[str, Any]], watch: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not docs or not watch:
        return []

    compiled = [
        (item, _compile_pattern(item["name"], item.get("aliases") or []))
        for item in watch
    ]

    matches: list[dict[str, Any]] = []
    for doc in docs:
        haystack = _haystack(doc)
        if not haystack:
            continue
        family = (doc.get("meta") or {}).get("family")
        weight = (doc.get("meta") or {}).get("weight") or 40
        for item, pattern in compiled:
            hit = pattern.search(haystack)
            if not hit:
                continue
            score = 60 + min(20, weight // 5)
            reason_bits = [f"name match in {family or 'unknown'}"]
            hint = (doc.get("meta") or {}).get("matched_dep_hint") or ""
            canonical = f"{item.get('ecosystem')}:{item.get('name')}".lower()
            if hint and hint == canonical:
                score += 15
                reason_bits.append("ecosystem-tagged source")
            matches.append(
                {
                    "doc": doc,
                    "watch_item": item,
                    "score": min(100, score),
                    "reason": " + ".join(reason_bits),
                }
            )
    log.info(
        "match %d candidate(s) over %d docs / %d watch items",
        len(matches),
        len(docs),
        len(watch),
    )
    return matches
