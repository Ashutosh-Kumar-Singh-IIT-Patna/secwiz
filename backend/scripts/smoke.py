"""End-to-end smoke test.

Run from the repo root with the venv activated (and ``backend`` on
``PYTHONPATH``)::

    python backend/scripts/smoke.py [--base-url http://localhost:8000] [--with-wire]

What it does:

1. ``GET /v1/healthz``
2. ``POST /v1/onboard`` for ``ash@example.com`` with two deps
   (``npm:lodash``, ``pypi:requests``).
3. ``POST /v1/runs/trigger`` (header ``X-Demo-Token``) and prints the run record.
4. Optionally re-runs with ``--with-wire`` to verify the Wire ingest path.
5. Prints store counts so you can confirm events / alerts persisted.

Requires a running ``uvicorn`` instance on the ``--base-url`` (defaults to
``http://localhost:8000``). Reads ``DEMO_TRIGGER_TOKEN`` and ``DATA_FILE``
from ``backend/.env`` via the same settings the server uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.store.json_store import get_store  # noqa: E402


_DEFAULT_DEPS = [
    {"ecosystem": "npm", "name": "lodash"},
    {"ecosystem": "pypi", "name": "requests"},
]


def _structured_only_config() -> dict:
    return {
        "families": {
            "structured_intel": {"enabled": True, "sources": ["osv", "nvd"]},
            "high_value_urls": {"enabled": False, "urls": []},
            "agentic_search": {"enabled": False, "max_runs_per_day": 0},
            "social_media": {"enabled": False, "wire_platform_slugs": []},
            "news": {"enabled": False, "wire_platform_slugs": []},
            "blogs": {"enabled": False, "wire_platform_slugs": []},
        },
        "wire_defaults": "all_enabled_except_auth_required",
    }


def _with_wire_config() -> dict:
    cfg = _structured_only_config()
    cfg["families"]["news"] = {
        "enabled": True,
        "wire_platform_slugs": ["github"],
    }
    return cfg


def _print(label: str, payload) -> None:
    print(f"\n--- {label} ---")
    print(json.dumps(payload, indent=2, default=str))


def main(base_url: str, with_wire: bool) -> int:
    settings = get_settings()
    store = get_store(settings.data_file_path)
    token = settings.DEMO_TRIGGER_TOKEN

    with httpx.Client(base_url=base_url, timeout=300.0) as client:
        r = client.get("/v1/healthz")
        r.raise_for_status()
        _print("healthz", r.json())

        config = _with_wire_config() if with_wire else _structured_only_config()
        body = {
            "email": "ash@example.com",
            "dependencies": _DEFAULT_DEPS,
            "source_config": config,
        }
        r = client.post("/v1/onboard", json=body)
        r.raise_for_status()
        onboard = r.json()
        _print("onboard", onboard)

        r = client.post(
            "/v1/runs/trigger",
            json={"user_id": onboard["user_id"]},
            headers={"X-Demo-Token": token},
        )
        r.raise_for_status()
        run = r.json()["run"]
        _print("run", run)

    snap = store.snapshot()
    print("\n--- store summary ---")
    print(
        json.dumps(
            {
                "users": len(snap["users"]),
                "watch_items": len(snap["watch_items"]),
                "source_documents": len(snap["source_documents"]),
                "security_events": len(snap["security_events"]),
                "alerts": len(snap["alerts"]),
                "runs": len(snap["runs"]),
            },
            indent=2,
        )
    )

    stats = run.get("stats") or {}
    if stats.get("docs", 0) == 0 and run.get("error"):
        print("\n[!] run had no docs and reported error:", run["error"])
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--with-wire",
        action="store_true",
        help="Enable Wire ingest with `github` slug for one extra Anakin call.",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.base_url, args.with_wire))
