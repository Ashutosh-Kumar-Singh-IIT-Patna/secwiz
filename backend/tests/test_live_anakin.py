"""Live Anakin tests — auto-skip when ``ANAKIN_API_KEY`` is missing.

Each test is marked ``live_anakin``; the marker is filtered in
``conftest.pytest_collection_modifyitems`` when no key is present, so a
no-key run still passes cleanly. With a key present these run inline and
burn a few credits per session — keep the count low.
"""

from __future__ import annotations

import os

import pytest

from app.services.anakin import wire
from app.services.anakin.client import AnakinClient
from app.services.pipeline.ingest import _choose_action, ingest_all


pytestmark = pytest.mark.live_anakin


async def test_live_list_catalogs_returns_items():
    async with AnakinClient(api_key=os.environ["ANAKIN_API_KEY"]) as client:
        items = await wire.list_catalogs(client)
    assert items, "Anakin returned an empty Wire catalog"
    # Sanity check: at least one catalog should NOT require auth so the V1
    # picker has anything to work with.
    assert any(not it.get("auth_required") for it in items)


async def test_live_get_catalog_for_public_slug_finds_action():
    """Pick a catalog known to expose non-auth actions and verify the picker.

    ``hackernews`` is public on Anakin's catalog (no login required), so the
    list+regex picker must return at least one usable action.
    """

    async with AnakinClient(api_key=os.environ["ANAKIN_API_KEY"]) as client:
        actions = await wire.list_actions(client, "hackernews")
    assert actions, "no hackernews actions returned"
    chosen = _choose_action(actions)
    assert chosen is not None
    assert chosen.get("auth_required") is False
    assert chosen.get("action_id")


async def test_live_ingest_all_with_wire_returns_docs():
    """Full ingest_all() against the live Anakin API.

    Limited to one watch item + one slug to cap credit usage. Asserts only
    that *something* came back through any family — the dynamic action
    picker is a heuristic, so we don't pin specific text.
    """

    cfg = {
        "families": {
            "structured_intel": {"enabled": True, "sources": ["osv", "nvd"]},
            "news": {"enabled": True, "wire_platform_slugs": ["hackernews"]},
            "high_value_urls": {"enabled": False, "urls": []},
            "agentic_search": {"enabled": False, "max_runs_per_day": 0},
        }
    }
    docs = await ingest_all(
        "u_live",
        watch=[{"name": "lodash", "ecosystem": "npm"}],
        cfg=cfg,
    )
    assert docs, "ingest_all returned 0 docs against live Anakin/OSV/NVD"
    families = {d["family"] for d in docs}
    # OSV/NVD should always produce something for lodash.
    assert "structured_intel" in families
