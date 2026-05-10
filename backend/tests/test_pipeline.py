"""Pipeline unit tests — normalize, match, cluster, score, alert.

No Anakin calls; we hand-build RawDoc dicts and feed them through the
deterministic stages.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.pipeline.alert import dispatch_alerts, render_alert
from app.services.pipeline.cluster import cluster_into_events
from app.services.pipeline.match import match_to_watchlist
from app.services.pipeline.normalize import normalize_docs
from app.services.pipeline.score import score_events, should_alert


def _doc(text: str, family: str = "structured_intel", **kwargs):
    base = {
        "url": "https://example.com/a",
        "publisher": "OSV",
        "title": "advisory",
        "text": text,
        "family": family,
        "weight": 90,
        "meta": {},
        "matched_dep_hint": "",
    }
    base.update(kwargs)
    return base


# ---------- normalize -----------------------------------------------------


def test_normalize_writes_documents(store):
    raws = [_doc("hello world"), _doc("second")]
    written = normalize_docs(store, raws)
    assert len(written) == 2
    assert all(rec["id"].startswith("sd_") for rec in written)
    assert all(rec["content_hash"].startswith("sha256:") for rec in written)


def test_normalize_skips_empty_text(store):
    written = normalize_docs(store, [_doc(""), _doc("   "), _doc("real content")])
    assert len(written) == 1
    assert written[0]["text"] == "real content"


def test_normalize_dedupe_within_run(store):
    written = normalize_docs(store, [_doc("dup"), _doc("dup"), _doc("uniq")])
    assert len(written) == 2


def test_normalize_dedupe_against_recent_history(store):
    normalize_docs(store, [_doc("first")])
    second_pass = normalize_docs(store, [_doc("first"), _doc("new")])
    assert {rec["text"] for rec in second_pass} == {"new"}


def test_normalize_dedup_disabled_when_window_zero(store, monkeypatch):
    """``DEDUP_WINDOW_HOURS=0`` makes every run re-emit every doc."""

    monkeypatch.setenv("DEDUP_WINDOW_HOURS", "0")
    from app.config import get_settings

    get_settings.cache_clear()

    normalize_docs(store, [_doc("first")])
    second_pass = normalize_docs(store, [_doc("first"), _doc("new")])
    # Both docs come back: the dedup-against-history skip is disabled.
    assert {rec["text"] for rec in second_pass} == {"first", "new"}


# ---------- match ---------------------------------------------------------


def _persisted(store, raws):
    return normalize_docs(store, raws)


def test_match_word_boundary_hit(store, make_watch_items):
    user, items = make_watch_items()  # lodash + requests
    docs = _persisted(
        store,
        [_doc("Critical RCE in lodash 4.17.20"), _doc("Unrelated kubernetes news")],
    )
    matches = match_to_watchlist(docs, items)
    assert len(matches) == 1
    assert matches[0]["watch_item"]["name"] == "lodash"


def test_match_ignores_substring_only(store, make_watch_items):
    """A word-boundary regex must NOT match `lodashed` in some other word."""

    user, items = make_watch_items(
        items=[{"ecosystem": "npm", "name": "lodash"}]
    )
    docs = _persisted(store, [_doc("we lodashedup the build")])
    assert match_to_watchlist(docs, items) == []


def test_match_aliases_hit(store, make_watch_items):
    user, items = make_watch_items(
        items=[
            {
                "ecosystem": "pypi",
                "name": "requests",
                "aliases": ["python-requests", "py-requests"],
            }
        ]
    )
    docs = _persisted(store, [_doc("CVE in py-requests <2.32")])
    matches = match_to_watchlist(docs, items)
    assert len(matches) == 1
    assert matches[0]["watch_item"]["name"] == "requests"


def test_match_ecosystem_hint_bumps_score(store, make_watch_items):
    user, items = make_watch_items(
        items=[{"ecosystem": "npm", "name": "lodash"}]
    )
    untagged = _persisted(store, [_doc("lodash advisory", matched_dep_hint="")])
    tagged = _persisted(
        store,
        [_doc("lodash advisory variant", matched_dep_hint="npm:lodash")],
    )
    a = match_to_watchlist(untagged, items)[0]["score"]
    b = match_to_watchlist(tagged, items)[0]["score"]
    assert b > a


# ---------- cluster -------------------------------------------------------


def test_cluster_groups_per_dep_per_day(store, make_watch_items):
    user, items = make_watch_items(
        items=[{"ecosystem": "npm", "name": "lodash"}]
    )
    docs = _persisted(
        store,
        [
            _doc("lodash bug A"),
            _doc("lodash bug B"),
            _doc("lodash bug C", family="wire", weight=80),
        ],
    )
    candidates = match_to_watchlist(docs, items)
    clusters = cluster_into_events(candidates)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["canonical_dep"] == "npm:lodash"
    assert len(cluster["signals"]) == 3
    assert cluster["event_id"].startswith("se_")


def test_cluster_separates_distinct_deps(store, make_watch_items):
    user, items = make_watch_items()  # lodash + requests
    docs = _persisted(
        store,
        [_doc("lodash issue"), _doc("requests issue")],
    )
    candidates = match_to_watchlist(docs, items)
    clusters = cluster_into_events(candidates)
    assert {c["canonical_dep"] for c in clusters} == {"npm:lodash", "pypi:requests"}


def test_cluster_event_id_is_deterministic_per_day(store, make_watch_items):
    user, items = make_watch_items(
        items=[{"ecosystem": "npm", "name": "lodash"}]
    )
    docs1 = _persisted(store, [_doc("lodash issue 1")])
    candidates1 = match_to_watchlist(docs1, items)

    docs2 = _persisted(store, [_doc("lodash issue 2 — different text")])
    candidates2 = match_to_watchlist(docs2, items)

    c1 = cluster_into_events(candidates1)[0]
    c2 = cluster_into_events(candidates2)[0]
    assert c1["event_id"] == c2["event_id"]


# ---------- score ---------------------------------------------------------


def test_score_critical_rce_pushes_severity():
    cluster = {
        "event_id": "se_x",
        "canonical_dep": "npm:lodash",
        "day": "today",
        "title": "RCE in lodash",
        "summary": "remote code execution via prototype pollution; CVE-2024-12345",
        "signals": [
            ({"text": "RCE confirmed; CVE-2024-12345"}, "structured_intel", 90),
        ],
        "matches": [],
        "doc_titles": ["RCE in lodash"],
    }
    [scored] = score_events([cluster])
    assert scored["severity"] >= 80
    assert scored["tier"] == "critical"
    assert scored["confidence"] >= 90


def test_score_low_signal_low_confidence():
    cluster = {
        "event_id": "se_y",
        "canonical_dep": "software:foo",
        "day": "today",
        "title": "tiny mention",
        "summary": "minor doc note",
        "signals": [({"text": "minor doc note"}, "url_scraper", 40)],
        "matches": [],
        "doc_titles": ["tiny"],
    }
    [scored] = score_events([cluster])
    assert scored["tier"] == "low"
    assert scored["confidence"] == 40


def test_should_alert_thresholds():
    assert should_alert({"severity": 90, "confidence": 80}) is True
    assert should_alert({"severity": 65, "confidence": 76}) is True
    assert should_alert({"severity": 65, "confidence": 70}) is False
    assert should_alert({"severity": 50, "confidence": 95}) is False


# ---------- alert dispatch ------------------------------------------------


def test_dispatch_writes_event_signal_match_alert(store, make_user):
    user = make_user()
    cluster = {
        "event_id": "se_dispatch",
        "canonical_dep": "npm:lodash",
        "title": "RCE in lodash",
        "summary": "summary",
        "severity": 88,
        "confidence": 90,
        "tier": "critical",
        "signals": [({"id": "sd_1", "url": "https://x", "text": "x"}, "structured_intel", 90)],
        "matches": [
            {
                "watch_item_id": "wi_1",
                "user_id": user["id"],
                "doc_id": "sd_1",
                "score": 80,
                "reason": "name match",
            }
        ],
    }
    sent = dispatch_alerts(store, user, [cluster], should_alert=should_alert)
    assert sent == 1
    snap = store.snapshot()
    assert "se_dispatch" in snap["security_events"]
    assert any(s["event_id"] == "se_dispatch" for s in snap["event_signals"])
    assert any(m["event_id"] == "se_dispatch" for m in snap["relevance_matches"])
    [alert] = list(snap["alerts"].values())
    assert alert["state"] == "dry_run"
    assert "[CRITICAL]" in alert["payload"]["subject"]


def test_dispatch_idempotent_for_same_event(store, make_user):
    user = make_user()
    cluster = {
        "event_id": "se_idem",
        "canonical_dep": "npm:lodash",
        "title": "RCE",
        "summary": "",
        "severity": 88,
        "confidence": 90,
        "tier": "critical",
        "signals": [({"id": "sd_1", "url": "https://x", "text": "x"}, "structured_intel", 90)],
        "matches": [],
    }
    sent_a = dispatch_alerts(store, user, [cluster], should_alert=should_alert)
    sent_b = dispatch_alerts(store, user, [cluster], should_alert=should_alert)
    assert sent_a == 1
    assert sent_b == 0  # already alerted


def test_render_alert_format(store, make_user):
    user = make_user()
    cluster = {
        "event_id": "se_render",
        "canonical_dep": "pypi:requests",
        "title": "auth bypass",
        "summary": "summary line",
        "severity": 75,
        "confidence": 80,
        "tier": "high",
        "signals": [
            ({"url": "https://osv.dev/x", "publisher": "OSV", "text": ""}, "structured_intel", 90),
        ],
        "matches": [],
    }
    msg = render_alert(user, cluster)
    assert msg.to == user["email"]
    assert "[HIGH]" in msg.subject
    assert "pypi:requests" in msg.subject
    assert "Severity" in msg.body and "Confidence" in msg.body
    assert "https://osv.dev/x" in msg.body
