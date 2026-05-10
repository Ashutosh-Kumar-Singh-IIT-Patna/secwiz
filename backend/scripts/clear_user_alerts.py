"""One-shot helper: drop all alerts for a given user so dedup will let
the next run re-fire them. Demo / debugging only — never call from app
code.

Usage:
    python scripts/clear_user_alerts.py u_01KR8KP5BJVHJVNWFS9N5MCX2D
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make sibling ``app`` importable when run as ``python scripts/...``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.store.json_store import get_store


def main(user_id: str) -> None:
    settings = get_settings()
    store = get_store(settings.data_file_path)

    snapshot = store.snapshot()
    alerts = snapshot.get("alerts", {})
    to_drop = [aid for aid, rec in alerts.items() if rec.get("user_id") == user_id]
    if not to_drop:
        print(f"no alerts for {user_id}")
        return

    # Use the public mutation surface — touch the in-memory db inside the
    # write context so the file lock + atomic rename both kick in.
    with store._write() as db:  # noqa: SLF001 — script-only utility
        for aid in to_drop:
            db["alerts"].pop(aid, None)
    print(f"cleared {len(to_drop)} alerts for {user_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/clear_user_alerts.py <user_id>")
        sys.exit(2)
    main(sys.argv[1])
