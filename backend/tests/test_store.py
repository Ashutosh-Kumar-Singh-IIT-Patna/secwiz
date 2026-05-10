"""JsonStore + per-section repo tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.store.ids import new_id
from app.store.json_store import JsonStore, get_store, reset_store_for_tests


def test_singleton_returns_same_instance(tmp_path):
    reset_store_for_tests()
    s1 = get_store(tmp_path / "a.json")
    s2 = get_store(tmp_path / "b.json")  # path ignored after first call
    assert s1 is s2
    reset_store_for_tests()


def test_initial_store_seeds_empty(tmp_path):
    store = JsonStore(tmp_path / "x.json")
    snap = store.snapshot()
    assert snap["users"] == {}
    assert snap["watch_items"] == {}
    assert snap["runs"] == []
    assert snap["wire_catalog_cache"] is None


def test_users_upsert_idempotent(store):
    a = store.users.upsert_by_email("a@example.com")
    b = store.users.upsert_by_email("A@example.com")  # case-insensitive
    assert a["id"] == b["id"]
    assert len(store.users.all()) == 1


def test_users_get_by_email(store):
    a = store.users.upsert_by_email("a@example.com")
    found = store.users.get_by_email("a@example.com")
    assert found is not None
    assert found["id"] == a["id"]
    assert store.users.get_by_email("nobody@example.com") is None


def test_watch_items_replace_for_user_clears_old(store, make_user):
    user = make_user("a@example.com")
    store.watch_items.replace_for_user(
        user["id"], [{"ecosystem": "npm", "name": "old"}]
    )
    assert {wi["name"] for wi in store.watch_items.by_user(user["id"])} == {"old"}

    store.watch_items.replace_for_user(
        user["id"], [{"ecosystem": "pypi", "name": "new"}]
    )
    items = store.watch_items.by_user(user["id"])
    assert {wi["name"] for wi in items} == {"new"}
    assert items[0]["ecosystem"] == "pypi"


def test_watch_items_per_user_isolation(store, make_user):
    a = make_user("a@example.com")
    b = make_user("b@example.com")
    store.watch_items.replace_for_user(a["id"], [{"name": "lodash"}])
    store.watch_items.replace_for_user(b["id"], [{"name": "requests"}])
    assert {wi["name"] for wi in store.watch_items.by_user(a["id"])} == {"lodash"}
    assert {wi["name"] for wi in store.watch_items.by_user(b["id"])} == {"requests"}


def test_source_config_replace(store, make_user):
    user = make_user()
    record = store.source_configs.replace_for_user(
        user["id"], {"families": {"structured_intel": {"enabled": True}}}
    )
    assert record["user_id"] == user["id"]
    fetched = store.source_configs.by_user(user["id"])
    assert fetched["config"]["families"]["structured_intel"]["enabled"] is True


def test_source_documents_dedupe_within_24h(store):
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    record = store.source_documents.insert(
        {
            "url": "https://example.com",
            "publisher": "x",
            "content_hash": "sha256:abc",
            "text": "hello",
        }
    )
    assert record["id"].startswith("sd_")
    assert store.source_documents.has_recent_hash("sha256:abc", cutoff) is True
    assert store.source_documents.has_recent_hash("sha256:def", cutoff) is False


def test_source_documents_old_hash_not_recent(store):
    store.source_documents.insert(
        {
            "url": "https://example.com",
            "content_hash": "sha256:old",
            "text": "x",
            "fetched_at": (
                datetime.now(tz=timezone.utc) - timedelta(days=2)
            ).isoformat(),
        }
    )
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    assert store.source_documents.has_recent_hash("sha256:old", cutoff) is False


def test_events_upsert_merges(store):
    ev_id = new_id("security_event")
    a = store.events.upsert(
        {"id": ev_id, "title": "first", "severity": 50, "confidence": 60}
    )
    b = store.events.upsert(
        {"id": ev_id, "title": "second", "severity": 90, "confidence": 70}
    )
    assert a["id"] == b["id"]
    snap = store.snapshot()["security_events"]
    assert snap[ev_id]["title"] == "second"
    assert snap[ev_id]["severity"] == 90
    assert len(snap) == 1


def test_event_signals_append(store):
    store.event_signals.append_many(
        [{"event_id": "se_1", "source_document_id": "sd_1", "family": "wire", "weight": 80}]
    )
    store.event_signals.append_many(
        [{"event_id": "se_1", "source_document_id": "sd_2", "family": "osv", "weight": 90}]
    )
    snap = store.snapshot()["event_signals"]
    assert len(snap) == 2


def test_alerts_dedupe_via_has_for(store, make_user):
    user = make_user()
    record = store.alerts.insert(
        {
            "user_id": user["id"],
            "event_id": "se_xyz",
            "severity": 80,
            "confidence": 80,
            "channel": "email",
            "state": "queued",
            "payload": {},
        }
    )
    assert store.alerts.has_for(user["id"], "se_xyz") is True
    assert store.alerts.has_for(user["id"], "se_other") is False
    store.alerts.update_state(record["id"], "sent")
    assert store.snapshot()["alerts"][record["id"]]["state"] == "sent"


def test_runs_append_records_id(store, make_user):
    user = make_user()
    record = store.runs.append(
        {"user_id": user["id"], "stats": {"docs": 0}, "error": None}
    )
    assert record["id"].startswith("rn_")
    assert len(store.runs.all()) == 1


def test_wire_catalog_cache_round_trip(store):
    items = [{"slug": "github", "name": "GitHub", "domain": "github.com"}]
    store.wire_catalog_cache.set(items)
    fetched = store.wire_catalog_cache.get()
    assert fetched["items"][0]["slug"] == "github"
    assert "fetched_at" in fetched


def test_atomic_write_persists_to_disk(tmp_path):
    path = tmp_path / "store.json"
    store = JsonStore(path)
    store.users.upsert_by_email("a@example.com")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert any(u["email"] == "a@example.com" for u in raw["users"].values())


def test_load_recovers_missing_keys(tmp_path):
    """Older snapshots that lack a section still load cleanly."""

    path = tmp_path / "store.json"
    path.write_text(json.dumps({"users": {}}), encoding="utf-8")
    store = JsonStore(path)
    snap = store.snapshot()
    assert snap["watch_items"] == {}
    assert snap["security_events"] == {}
    assert snap["wire_catalog_cache"] is None


def test_ids_have_correct_prefixes():
    assert new_id("user").startswith("u_")
    assert new_id("watch_item").startswith("wi_")
    assert new_id("source_document").startswith("sd_")
    assert new_id("security_event").startswith("se_")
    assert new_id("alert").startswith("al_")
    assert new_id("run").startswith("rn_")
    with pytest.raises(KeyError):
        new_id("nonsense")
