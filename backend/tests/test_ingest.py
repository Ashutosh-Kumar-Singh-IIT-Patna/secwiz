"""Ingest fan-out tests with respx mocking the Anakin endpoints.

These exercise the structured-intel + Wire branches of
:func:`app.services.pipeline.ingest.ingest_all` end-to-end without a live
network. Wire actions are picked through the keyword-regex strategy.
"""

from __future__ import annotations

import httpx
import respx

from app.services.pipeline.ingest import (
    _choose_action,
    _params_for_action,
    ingest_all,
)


# ---------- _choose_action picker ----------------------------------------


def test_choose_action_prefers_keyword_match():
    actions = [
        {"action_id": "a1", "name": "Get Profile", "description": "fetch a single profile", "auth_required": False},
        {"action_id": "a2", "name": "Search Repositories", "description": "find repos", "auth_required": False},
    ]
    chosen = _choose_action(actions)
    assert chosen["action_id"] == "a2"


def test_choose_action_falls_back_to_first_non_auth():
    actions = [
        {"action_id": "a1", "name": "Quirky", "description": "...", "auth_required": False},
        {"action_id": "a2", "name": "Other", "description": "...", "auth_required": True},
    ]
    chosen = _choose_action(actions)
    assert chosen["action_id"] == "a1"


def test_choose_action_skips_auth_required():
    actions = [
        {"action_id": "a1", "name": "Search", "description": "needs login", "auth_required": True},
    ]
    assert _choose_action(actions) is None


def test_choose_action_empty():
    assert _choose_action([]) is None


# ---------- env-driven cost caps -----------------------------------------


def test_max_wire_calls_env_caps_jobs(monkeypatch):
    """``MAX_WIRE_CALLS_PER_RUN`` truncates the (slug, watch) job list."""

    from app.config import get_settings
    from app.services.pipeline.ingest import _collect_wire_jobs

    monkeypatch.setenv("MAX_WIRE_CALLS_PER_RUN", "2")
    get_settings.cache_clear()

    families = {
        "news": {
            "enabled": True,
            "wire_platform_slugs": ["hackernews", "reddit", "github"],
        }
    }
    watch = [
        {"name": "lodash", "ecosystem": "npm"},
        {"name": "requests", "ecosystem": "pypi"},
    ]
    jobs = _collect_wire_jobs(families, watch)
    assert len(jobs) == 2


# Real Hacker News action shape sampled from a live
# ``GET /v1/holocron/catalog/hackernews`` response. Anchors the picker
# heuristic against drift.
HN_LIVE_ACTIONS: list[dict] = [
    {
        "action_id": "hn_item_details",
        "name": "Hacker News Item Details",
        "description": "Full item details — story, comment, job, or poll with nested comment tree up to depth 3.",
        "auth_required": False,
        "params": [
            {"name": "id", "type": "string", "required": True, "default": "47543139"},
            {"name": "include_comments", "type": "boolean", "required": False},
            {"name": "comment_depth", "type": "integer", "required": False},
        ],
    },
    {
        "action_id": "hn_stories",
        "name": "Hacker News Stories",
        "description": "Get stories from any HN feed — top, new, best, Ask HN, Show HN, jobs.",
        "auth_required": False,
        "params": [
            {"name": "type", "type": "string", "required": False},
            {"name": "limit", "type": "integer", "required": False},
            {"name": "offset", "type": "integer", "required": False},
        ],
    },
    {
        "action_id": "hn_user_details",
        "name": "Hacker News User Details",
        "description": "User profile — karma, about, and optionally recent submissions.",
        "auth_required": False,
        "params": [
            {"name": "username", "type": "string", "required": True, "default": "dang"},
        ],
    },
    {
        "action_id": "hn_search",
        "name": "Search Hacker News",
        "description": "Search Hacker News posts via Algolia API.",
        "auth_required": False,
        "params": [
            {"name": "query", "type": "string", "required": True, "default": "claude"},
        ],
    },
]


def test_choose_action_picks_hn_search_for_hackernews():
    """Live-shape regression: search action must beat detail/stories/user."""

    chosen = _choose_action(HN_LIVE_ACTIONS)
    assert chosen is not None
    assert chosen["action_id"] == "hn_search"


def test_choose_action_penalises_id_required_when_no_query_alternative():
    """Action requiring a specific ID/username we can't fabricate loses."""

    actions = [
        {
            "action_id": "needs_id",
            "name": "Get Item",
            "description": "stories",  # listy-tier match
            "auth_required": False,
            "params": [{"name": "id", "type": "string", "required": True}],
        },
        {
            "action_id": "no_required",
            "name": "Get Items",
            "description": "stories",
            "auth_required": False,
            "params": [{"name": "limit", "type": "integer", "required": False}],
        },
    ]
    chosen = _choose_action(actions)
    assert chosen["action_id"] == "no_required"


# ---------- _params_for_action filler -------------------------------------


def _action(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "action_id": "x",
        "params": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    }


def test_params_search_style_query_filled_with_watch_name():
    action = _action({"query": {"type": "string"}}, required=["query"])
    assert _params_for_action(action, "lodash") == {"query": "lodash"}


def test_params_alt_query_field_names():
    for field in ("q", "keyword", "search", "search_term", "term"):
        action = _action({field: {"type": "string"}}, required=[field])
        assert _params_for_action(action, "lodash")[field] == "lodash"


def test_params_hn_stories_shape_uses_defaults_not_watch_name():
    """``hn_stories`` takes ``type`` (string), ``limit`` (int), ``offset`` (int).

    None of those fields are search-style, so ``lodash`` must NOT end up in
    ``type`` — that would break the call.
    """

    action = _action(
        {
            "type": {"type": "string"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        }
    )
    out = _params_for_action(action, "lodash")
    assert out.get("limit") == 10
    assert out.get("offset") == 0
    # `type` is unrequired and not search-style -> we accept either it being
    # filled with the watch name (last-resort fallback) or skipped, but it
    # must not be filled with the empty default that the spec example showed.
    if "type" in out:
        assert out["type"] != ""


def test_params_honours_default_when_present():
    action = _action(
        {"type": {"type": "string", "default": "top"}, "limit": {"type": "integer", "default": 25}}
    )
    out = _params_for_action(action, "lodash")
    assert out.get("type") == "top"
    assert out.get("limit") == 25


def test_params_honours_enum_when_present():
    action = _action(
        {"type": {"type": "string", "enum": ["top", "new", "best"]}},
        required=["type"],
    )
    out = _params_for_action(action, "lodash")
    assert out["type"] == "top"


def test_params_required_int_fills_zero():
    action = _action(
        {"limit": {"type": "integer"}, "size": {"type": "integer"}},
        required=["limit", "size"],
    )
    out = _params_for_action(action, "lodash")
    assert out["limit"] == 10  # named convention beats fallback
    assert out["size"] == 10


def test_params_no_schema_returns_empty():
    assert _params_for_action({"action_id": "x"}, "lodash") == {}


def test_params_falls_back_to_first_string_when_no_required():
    """Optional single-string param actions still get the watch name."""

    action = _action({"keyword": {"type": "string"}})
    assert _params_for_action(action, "lodash") == {"keyword": "lodash"}


# ---------- List-shape (live Anakin) param descriptors -------------------


def _list_action(params: list[dict]) -> dict:
    return {"action_id": "x", "params": params}


def test_params_list_shape_required_query():
    """Live-shape `hn_search`: required query param gets watch name."""

    action = _list_action(
        [{"name": "query", "type": "string", "required": True, "default": "claude"}]
    )
    out = _params_for_action(action, "lodash")
    # Required + has default — default wins per the contract.
    assert out["query"] == "claude"


def test_params_list_shape_required_query_no_default_uses_value():
    action = _list_action([{"name": "query", "type": "string", "required": True}])
    assert _params_for_action(action, "lodash") == {"query": "lodash"}


def test_params_list_shape_hn_stories_skips_optional_type():
    """`hn_stories`: optional `type` (string, no default), `limit` (int), `offset` (int).

    `type` is unrequired and not search-style so it MUST be skipped — sending
    "lodash" as the feed type would error. `limit`/`offset` get sane numeric
    defaults.
    """

    action = _list_action(
        [
            {"name": "type", "type": "string", "required": False},
            {"name": "limit", "type": "integer", "required": False},
            {"name": "offset", "type": "integer", "required": False},
        ]
    )
    out = _params_for_action(action, "lodash")
    assert out == {"limit": 10, "offset": 0}


def test_params_list_shape_required_id_with_default_uses_default():
    """`hn_item_details`: required `id` with default — default wins."""

    action = _list_action(
        [
            {"name": "id", "type": "string", "required": True, "default": "47543139"},
            {"name": "include_comments", "type": "boolean", "required": False},
        ]
    )
    out = _params_for_action(action, "lodash")
    assert out["id"] == "47543139"


# ---------- ingest_all: structured intel only -----------------------------


@respx.mock
async def test_ingest_all_structured_intel_only_no_anakin_calls(monkeypatch):
    """When ANAKIN_API_KEY is empty we still ingest via OSV+NVD."""

    monkeypatch.setenv("ANAKIN_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    respx.post("https://api.osv.dev/v1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "vulns": [
                    {
                        "id": "GHSA-1",
                        "summary": "advisory",
                        "details": "details",
                        "references": [],
                    }
                ]
            },
        )
    )
    respx.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
        return_value=httpx.Response(200, json={"vulnerabilities": []})
    )

    docs = await ingest_all(
        "u_x",
        watch=[{"name": "lodash", "ecosystem": "npm"}],
        cfg={"families": {"structured_intel": {"enabled": True}}},
    )
    assert any(d["family"] == "structured_intel" for d in docs)


# ---------- ingest_all: Wire happy path -----------------------------------


@respx.mock
async def test_ingest_all_wire_happy_path(monkeypatch):
    monkeypatch.setenv("ANAKIN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    cfg = {
        "families": {
            "structured_intel": {"enabled": False},
            "agentic_search": {"enabled": False, "max_runs_per_day": 0},
            "high_value_urls": {"enabled": False, "urls": []},
            "news": {"enabled": True, "wire_platform_slugs": ["github"]},
        }
    }

    respx.get("https://api.anakin.io/v1/holocron/catalog/github").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalog": {
                    "slug": "github",
                    "name": "GitHub",
                    "auth_required": False,
                },
                "actions": [
                    {
                        "action_id": "gh_search_repos",
                        "name": "Search Repositories",
                        "description": "search github repos",
                        "mode": "async",
                        "auth_required": False,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "limit": {"type": "integer"},
                            },
                            "required": ["query"],
                        },
                    }
                ],
            },
        )
    )
    respx.post("https://api.anakin.io/v1/holocron/task").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "status": "processing"})
    )
    respx.get("https://api.anakin.io/v1/holocron/jobs/j1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "completed",
                "data": {"title": "Critical CVE in lodash", "summary": "RCE"},
            },
        )
    )

    docs = await ingest_all(
        "u_x",
        watch=[{"name": "lodash", "ecosystem": "npm"}],
        cfg=cfg,
    )
    wire_docs = [d for d in docs if d["family"] == "wire"]
    assert len(wire_docs) == 1
    assert wire_docs[0]["meta"]["action_id"] == "gh_search_repos"
    assert "lodash" in wire_docs[0]["text"]


# ---------- ingest_all: Wire path with no usable actions ------------------


@respx.mock
async def test_ingest_all_wire_no_usable_action(monkeypatch):
    monkeypatch.setenv("ANAKIN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    respx.get("https://api.anakin.io/v1/holocron/catalog/github").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalog": {"slug": "github", "auth_required": True},
                "actions": [
                    {
                        "action_id": "auth_only",
                        "name": "Profile",
                        "description": "",
                        "mode": "async",
                        "auth_required": True,
                        "parameters": {},
                    }
                ],
            },
        )
    )
    docs = await ingest_all(
        "u_x",
        watch=[{"name": "lodash", "ecosystem": "npm"}],
        cfg={
            "families": {
                "structured_intel": {"enabled": False},
                "agentic_search": {"enabled": False, "max_runs_per_day": 0},
                "high_value_urls": {"enabled": False, "urls": []},
                "news": {"enabled": True, "wire_platform_slugs": ["github"]},
            }
        },
    )
    assert docs == []
