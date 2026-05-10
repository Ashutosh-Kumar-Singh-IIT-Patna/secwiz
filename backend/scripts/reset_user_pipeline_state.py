"""Drop all pipeline state for one user so the next run re-ingests fresh.

Removes:
  - alerts (so dedup won't block re-firing)
  - relevance_matches for the user's watch_items
  - source_documents whose ``content_hash`` is referenced only by this
    user's matches (V1: we just nuke ALL source_documents — they're a
    cache, not a source of truth, and dedup is what we're trying to
    bypass anyway)
  - security_events whose canonical_dep matches one of this user's
    watch items (best-effort — events are cross-user but in V1 each user
    runs their own pipeline so collisions are rare)
  - event_signals tied to those events

Keeps users, watch_items, source_configs, runs.

Usage:
    python scripts/reset_user_pipeline_state.py u_01KR8KP5BJVHJVNWFS9N5MCX2D
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.store.json_store import get_store


def main(user_id: str) -> None:
    settings = get_settings()
    store = get_store(settings.data_file_path)

    snapshot = store.snapshot()
    if user_id not in snapshot.get("users", {}):
        print(f"unknown user: {user_id}")
        return

    watch_items = snapshot.get("watch_items", {})
    user_watch_ids = {
        wid for wid, rec in watch_items.items() if rec.get("user_id") == user_id
    }
    user_canonicals = {
        f"{rec.get('ecosystem')}:{rec.get('name')}".lower()
        for rec in watch_items.values()
        if rec.get("user_id") == user_id
    }

    relevance = snapshot.get("relevance_matches", [])
    user_event_ids = {
        m.get("event_id")
        for m in relevance
        if m.get("watch_item_id") in user_watch_ids
    }

    events = snapshot.get("security_events", {})
    for eid, ev in events.items():
        if (ev.get("canonical_dep") or "").lower() in user_canonicals:
            user_event_ids.add(eid)

    with store._write() as db:  # noqa: SLF001 — script-only utility
        cleared = {
            "alerts": 0,
            "matches": 0,
            "events": 0,
            "signals": 0,
            "documents": 0,
        }

        for aid, rec in list(db["alerts"].items()):
            if rec.get("user_id") == user_id:
                db["alerts"].pop(aid)
                cleared["alerts"] += 1

        before = len(db["relevance_matches"])
        db["relevance_matches"] = [
            m
            for m in db["relevance_matches"]
            if m.get("watch_item_id") not in user_watch_ids
        ]
        cleared["matches"] = before - len(db["relevance_matches"])

        for eid in list(db["security_events"].keys()):
            if eid in user_event_ids:
                db["security_events"].pop(eid)
                cleared["events"] += 1

        before = len(db["event_signals"])
        db["event_signals"] = [
            s for s in db["event_signals"] if s.get("event_id") not in user_event_ids
        ]
        cleared["signals"] = before - len(db["event_signals"])

        # Documents are a content-addressed cache; in V1 we just nuke
        # them so dedup doesn't block fresh ingests.
        cleared["documents"] = len(db["source_documents"])
        db["source_documents"] = {}

    print(f"reset user={user_id}")
    for k, v in cleared.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/reset_user_pipeline_state.py <user_id>")
        sys.exit(2)
    main(sys.argv[1])
