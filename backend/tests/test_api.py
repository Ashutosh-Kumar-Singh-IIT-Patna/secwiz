"""End-to-end API tests via FastAPI TestClient.

Anakin calls are mocked with respx. The full pipeline (ingest → score →
alert) runs synchronously thanks to eager Celery, so a single
``POST /v1/runs/trigger`` covers the whole stack.
"""

from __future__ import annotations

import httpx
import pytest
import respx


def _onboard_body(**overrides) -> dict:
    body = {
        "email": "ash@example.com",
        "dependencies": [
            {"ecosystem": "npm", "name": "lodash"},
            {"ecosystem": "pypi", "name": "requests"},
        ],
        "source_config": {
            "families": {
                "structured_intel": {"enabled": True, "sources": ["osv", "nvd"]},
                "high_value_urls": {"enabled": False, "urls": []},
                "agentic_search": {"enabled": False, "max_runs_per_day": 0},
                "social_media": {"enabled": False, "wire_platform_slugs": []},
                "news": {"enabled": False, "wire_platform_slugs": []},
                "blogs": {"enabled": False, "wire_platform_slugs": []},
            },
            "wire_defaults": "all_enabled_except_auth_required",
        },
    }
    body.update(overrides)
    return body


# ---------- healthz -------------------------------------------------------


def test_healthz(fastapi_client):
    r = fastapi_client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------- onboard validation -------------------------------------------


def test_onboard_happy_path(fastapi_client):
    r = fastapi_client.post("/v1/onboard", json=_onboard_body())
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert payload["watch_item_count"] == 2
    assert payload["user_id"].startswith("u_")


def test_onboard_rejects_bad_email(fastapi_client):
    r = fastapi_client.post(
        "/v1/onboard", json=_onboard_body(email="not-an-email")
    )
    assert r.status_code == 422


def test_onboard_requires_at_least_one_dep(fastapi_client):
    r = fastapi_client.post("/v1/onboard", json=_onboard_body(dependencies=[]))
    assert r.status_code == 422


def test_onboard_unknown_ecosystem_normalises_to_software(fastapi_client):
    r = fastapi_client.post(
        "/v1/onboard",
        json=_onboard_body(
            dependencies=[{"ecosystem": "weirdsystem", "name": "thing"}]
        ),
    )
    assert r.status_code == 200
    user_id = r.json()["user_id"]
    from app.store.json_store import get_store

    [item] = get_store().watch_items.by_user(user_id)
    assert item["ecosystem"] == "software"


def test_onboard_idempotent_replaces_watchlist(fastapi_client):
    r1 = fastapi_client.post(
        "/v1/onboard",
        json=_onboard_body(
            dependencies=[{"ecosystem": "npm", "name": "lodash"}]
        ),
    )
    user_id = r1.json()["user_id"]
    r2 = fastapi_client.post(
        "/v1/onboard",
        json=_onboard_body(
            dependencies=[{"ecosystem": "pypi", "name": "requests"}]
        ),
    )
    assert r2.json()["user_id"] == user_id
    from app.store.json_store import get_store

    items = get_store().watch_items.by_user(user_id)
    assert {i["name"] for i in items} == {"requests"}


# ---------- wire-catalog --------------------------------------------------


@respx.mock
def test_wire_catalog_proxies_and_caches(fastapi_client, monkeypatch):
    monkeypatch.setenv("ANAKIN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    catalog_route = respx.get("https://api.anakin.io/v1/holocron/catalog").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalog": [
                    {
                        "slug": "github",
                        "name": "GitHub",
                        "domain": "github.com",
                        "category": "developer-tools",
                        "auth_required": False,
                    },
                    {
                        "slug": "linkedin",
                        "name": "LinkedIn",
                        "domain": "linkedin.com",
                        "category": "social",
                        "auth_required": True,
                    },
                ]
            },
        )
    )

    r1 = fastapi_client.get("/v1/wire-catalog")
    assert r1.status_code == 200
    body1 = r1.json()
    assert {it["slug"] for it in body1["items"]} == {"github", "linkedin"}
    assert body1["cached"] is False

    r2 = fastapi_client.get("/v1/wire-catalog")
    assert r2.json()["cached"] is True
    assert catalog_route.call_count == 1  # second hit served from cache


def test_wire_catalog_fails_without_key_and_no_cache(fastapi_client, monkeypatch):
    monkeypatch.setenv("ANAKIN_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    r = fastapi_client.get("/v1/wire-catalog")
    assert r.status_code == 503


# ---------- runs/trigger --------------------------------------------------


def test_trigger_requires_demo_token(fastapi_client):
    r1 = fastapi_client.post("/v1/onboard", json=_onboard_body())
    user_id = r1.json()["user_id"]
    r = fastapi_client.post("/v1/runs/trigger", json={"user_id": user_id})
    assert r.status_code == 401


def test_trigger_404_on_unknown_user(fastapi_client):
    r = fastapi_client.post(
        "/v1/runs/trigger",
        json={"user_id": "u_doesnotexist"},
        headers={"X-Demo-Token": "test-token"},
    )
    assert r.status_code == 404


@respx.mock
def test_trigger_runs_full_pipeline_with_mocked_osv(fastapi_client, monkeypatch):
    """End-to-end: onboard → trigger → OSV mock → alert dry-run logged."""

    monkeypatch.setenv("ANAKIN_API_KEY", "")  # force structured-intel-only path
    from app.config import get_settings

    get_settings.cache_clear()

    osv_route = respx.post("https://api.osv.dev/v1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "vulns": [
                    {
                        "id": "GHSA-test",
                        "summary": "RCE in lodash via prototype pollution",
                        "details": "Critical RCE; CVE-2024-99999",
                        "references": [{"url": "https://example.com"}],
                    }
                ]
            },
        )
    )
    nvd_route = respx.get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0"
    ).mock(return_value=httpx.Response(200, json={"vulnerabilities": []}))

    r1 = fastapi_client.post(
        "/v1/onboard",
        json=_onboard_body(
            dependencies=[{"ecosystem": "npm", "name": "lodash"}]
        ),
    )
    user_id = r1.json()["user_id"]

    r2 = fastapi_client.post(
        "/v1/runs/trigger",
        json={"user_id": user_id},
        headers={"X-Demo-Token": "test-token"},
    )
    assert r2.status_code == 200
    run = r2.json()["run"]
    assert run["error"] is None
    stats = run["stats"]
    assert stats["docs"] >= 1
    assert stats["events"] >= 1
    assert stats["alerts_sent"] >= 1
    assert osv_route.called
    assert nvd_route.called

    from app.store.json_store import get_store

    snap = get_store().snapshot()
    assert len(snap["alerts"]) >= 1
    [alert] = list(snap["alerts"].values())
    assert alert["state"] == "dry_run"
    assert "lodash" in alert["payload"]["subject"].lower()
