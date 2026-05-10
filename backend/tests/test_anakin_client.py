"""Anakin wrapper tests using respx to mock httpx."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.anakin import agentic, search, structured_intel, url_scraper, wire
from app.services.anakin.client import AnakinClient, AnakinError


# ---------- client core ---------------------------------------------------


@respx.mock
async def test_client_sends_x_api_key():
    route = respx.get("https://api.anakin.io/v1/healthcheck").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = AnakinClient(api_key="test-key")
    async with client:
        await client.get("/healthcheck")
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_client_raises_on_4xx():
    respx.post("https://api.anakin.io/v1/holocron/task").mock(
        return_value=httpx.Response(401, json={"error": {"code": "AUTH_REQUIRED"}})
    )
    client = AnakinClient(api_key="test-key")
    async with client:
        with pytest.raises(AnakinError) as err:
            await client.post("/holocron/task", json={})
    assert err.value.status == 401


# ---------- wire ----------------------------------------------------------


@respx.mock
async def test_wire_list_catalogs_unwraps_list():
    respx.get("https://api.anakin.io/v1/holocron/catalog").mock(
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
                    }
                ]
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        items = await wire.list_catalogs(client)
    assert items[0]["slug"] == "github"


@respx.mock
async def test_wire_search_actions_passes_filters():
    route = respx.get("https://api.anakin.io/v1/holocron/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    client = AnakinClient(api_key="k")
    async with client:
        await wire.search_actions(client, query="lodash", catalog="github", auth=False)

    assert route.called
    qs = dict(route.calls.last.request.url.params)
    assert qs == {"q": "lodash", "catalog": "github", "auth": "false"}


@respx.mock
async def test_wire_run_action_polls_until_completed():
    respx.post("https://api.anakin.io/v1/holocron/task").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "status": "processing"})
    )
    poll = respx.get("https://api.anakin.io/v1/holocron/jobs/j1")
    poll.side_effect = [
        httpx.Response(200, json={"status": "processing"}),
        httpx.Response(200, json={"status": "completed", "data": {"hits": ["x"]}}),
    ]
    client = AnakinClient(api_key="k")
    async with client:
        result = await wire.run_action(client, action_id="some_action", params={"q": "x"})
    assert result["status"] == "completed"
    assert result["data"] == {"hits": ["x"]}
    assert poll.call_count == 2


@respx.mock
async def test_wire_submit_task_body_matches_docs():
    """Lock the POST body shape against the docs example.

    Per docs: ``{action_id, credential_id?, params?}``. Optional fields
    must be omitted when not provided, never sent as ``null``/``{}``.
    """

    import json

    route = respx.post("https://api.anakin.io/v1/holocron/task").mock(
        return_value=httpx.Response(202, json={"job_id": "j", "status": "processing"})
    )
    client = AnakinClient(api_key="k")

    async with client:
        await wire.submit_task(client, action_id="ab_search_listings", params={"query": "loft"})
    body = json.loads(route.calls.last.request.content)
    assert body == {"action_id": "ab_search_listings", "params": {"query": "loft"}}
    assert "credential_id" not in body

    async with client:
        await wire.submit_task(
            client,
            action_id="li_profile_scrape",
            params={"profile_url": "https://x"},
            credential_id="11111111-2222-3333-4444-555555555555",
        )
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "action_id": "li_profile_scrape",
        "params": {"profile_url": "https://x"},
        "credential_id": "11111111-2222-3333-4444-555555555555",
    }

    async with client:
        await wire.submit_task(client, action_id="hn_stories")
    body = json.loads(route.calls.last.request.content)
    assert body == {"action_id": "hn_stories"}
    assert "params" not in body


@respx.mock
async def test_wire_get_catalog_returns_full_payload():
    """`GET /v1/holocron/catalog/{slug}` returns ``{catalog, actions}``."""

    respx.get("https://api.anakin.io/v1/holocron/catalog/airbnb").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalog": {"slug": "airbnb", "name": "Airbnb"},
                "actions": [
                    {"action_id": "ab_search_listings", "name": "Search Listings"}
                ],
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        payload = await wire.get_catalog(client, "airbnb")
    assert payload["catalog"]["slug"] == "airbnb"
    assert payload["actions"][0]["action_id"] == "ab_search_listings"


@respx.mock
async def test_wire_list_actions_unwraps_actions_array():
    respx.get("https://api.anakin.io/v1/holocron/catalog/github").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalog": {"slug": "github"},
                "actions": [
                    {"action_id": "gh_search_repos", "auth_required": False},
                    {"action_id": "gh_list_advisories", "auth_required": False},
                ],
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        actions = await wire.list_actions(client, "github")
    assert [a["action_id"] for a in actions] == ["gh_search_repos", "gh_list_advisories"]


@respx.mock
async def test_wire_run_action_sync_mode_returns_inline_data():
    """Sync actions can return ``{status: completed, data: ...}`` from the POST.

    No ``job_id`` means we MUST NOT poll — propagating the submission
    payload as-is is the documented behaviour.
    """

    respx.post("https://api.anakin.io/v1/holocron/task").mock(
        return_value=httpx.Response(
            200, json={"status": "completed", "data": {"hits": [1, 2, 3]}}
        )
    )
    poll_route = respx.get("https://api.anakin.io/v1/holocron/jobs/anything")
    client = AnakinClient(api_key="k")
    async with client:
        result = await wire.run_action(client, action_id="sync_action", params={"q": "x"})
    assert result["status"] == "completed"
    assert result["data"] == {"hits": [1, 2, 3]}
    assert poll_route.call_count == 0


@respx.mock
async def test_wire_search_actions_omits_unset_filters():
    """Calling `search_actions()` with no filters sends an empty querystring.

    Regression-guards against accidental ``auth=false`` defaults that
    triggered live 500s previously.
    """

    route = respx.get("https://api.anakin.io/v1/holocron/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    client = AnakinClient(api_key="k")
    async with client:
        await wire.search_actions(client)
    qs = dict(route.calls.last.request.url.params)
    assert qs == {}


# ---------- url scraper ---------------------------------------------------


@respx.mock
async def test_url_scraper_single_polls_completed():
    respx.post("https://api.anakin.io/v1/url-scraper").mock(
        return_value=httpx.Response(202, json={"jobId": "u1", "status": "pending"})
    )
    respx.get("https://api.anakin.io/v1/url-scraper/u1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "u1",
                "status": "completed",
                "url": "https://example.com",
                "markdown": "# hi",
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        result = await url_scraper.scrape_url(client, "https://example.com")
    assert result["status"] == "completed"
    assert result["markdown"] == "# hi"


@respx.mock
async def test_url_scraper_batch_rejects_too_many():
    client = AnakinClient(api_key="k")
    async with client:
        with pytest.raises(ValueError):
            await url_scraper.submit_batch(client, urls=[f"https://x.com/{i}" for i in range(11)])


# ---------- agentic -------------------------------------------------------


@respx.mock
async def test_agentic_research_returns_completed():
    respx.post("https://api.anakin.io/v1/agentic-search").mock(
        return_value=httpx.Response(202, json={"job_id": "a1", "status": "pending"})
    )
    respx.get("https://api.anakin.io/v1/agentic-search/a1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "completed",
                "id": "a1",
                "generatedJson": {"summary": "found 3 issues"},
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        result = await agentic.research(client, "test prompt")
    assert result["status"] == "completed"
    assert result["generatedJson"]["summary"] == "found 3 issues"


# ---------- search (sync) -------------------------------------------------


@respx.mock
async def test_search_returns_results_array():
    respx.post("https://api.anakin.io/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "s1",
                "results": [
                    {"url": "https://a.com", "title": "A", "snippet": "x"},
                ],
            },
        )
    )
    client = AnakinClient(api_key="k")
    async with client:
        rows = await search.search(client, "lodash CVE", limit=3)
    assert rows[0]["title"] == "A"


# ---------- structured intel (OSV / NVD) ---------------------------------


@respx.mock
async def test_osv_returns_normalized_advisories():
    respx.post("https://api.osv.dev/v1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "vulns": [
                    {
                        "id": "GHSA-xxxx",
                        "summary": "RCE in pkg",
                        "details": "details body",
                        "references": [{"url": "https://x"}],
                        "severity": [{"score": "9.8"}],
                    }
                ]
            },
        )
    )
    docs = await structured_intel.query_osv("lodash", "npm")
    assert len(docs) == 1
    assert docs[0]["publisher"] == "OSV"
    assert docs[0]["title"] == "RCE in pkg"
    assert "GHSA-xxxx" in docs[0]["url"]


async def test_osv_skips_unknown_ecosystem():
    docs = await structured_intel.query_osv("foo", "weirdsystem")
    assert docs == []


@respx.mock
async def test_osv_swallows_upstream_failure():
    respx.post("https://api.osv.dev/v1/query").mock(
        return_value=httpx.Response(500, json={"err": "x"})
    )
    docs = await structured_intel.query_osv("lodash", "npm")
    assert docs == []


@respx.mock
async def test_nvd_normalizes_to_doc_dict():
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(
            200,
            json={
                "vulnerabilities": [
                    {
                        "cve": {
                            "id": "CVE-2024-1",
                            "descriptions": [
                                {"lang": "en", "value": "auth bypass"},
                            ],
                        }
                    }
                ]
            },
        )
    )
    docs = await structured_intel.query_nvd("lodash")
    assert docs[0]["title"] == "CVE-2024-1"
    assert docs[0]["publisher"] == "NVD"
    assert "auth bypass" in docs[0]["text"]
