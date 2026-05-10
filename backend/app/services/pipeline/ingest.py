"""Source-family fan-out.

The function :func:`ingest_all` accepts the user's ``source_config`` plus
their watchlist and returns a flat list of ``RawDoc`` dicts ready for
:mod:`.normalize`. Each branch is wrapped in a try/except so a single flaky
source can't sink the whole run.

A ``RawDoc`` is intentionally a plain dict, not a Pydantic model — it
simplifies merging across families and lets each ingest path attach
free-form ``meta`` without a schema migration.

Shape::

    {
        "url": str,
        "publisher": str,
        "title": str,
        "text": str,
        "family": "structured_intel" | "wire" | "agentic" | "url_scraper" | ...,
        "weight": int,             # source-family weight (0-100)
        "meta": dict,
        "matched_dep_hint": str,   # canonical "ecosystem:name" hint when known
    }
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Iterable

from ...config import get_settings
from ..anakin import agentic as agentic_search
from ..anakin import structured_intel
from ..anakin import url_scraper, wire
from ..anakin.client import AnakinClient, AnakinError

log = logging.getLogger(__name__)


_FAMILY_WEIGHTS: dict[str, int] = {
    "structured_intel": 90,
    "wire": 80,
    "agentic": 50,
    "url_scraper": 40,
    "search": 50,
}

# Per-run budget caps live in settings so they're tunable per environment
# without code changes. Hackathon defaults keep a single hourly tick under
# a handful of Anakin credits.


def _canonical(dep: dict[str, Any]) -> str:
    return f"{dep.get('ecosystem', 'software')}:{dep.get('name', '')}".lower()


async def ingest_all(
    user_id: str,
    watch: list[dict[str, Any]],
    cfg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Run every enabled source family for one user.

    Returns a flat list of RawDoc dicts (de-duplication happens later in
    :mod:`.normalize`).
    """

    families = (cfg or {}).get("families", {}) or {}
    settings = get_settings()
    docs: list[dict[str, Any]] = []

    if not watch:
        log.info("ingest user=%s: empty watchlist, nothing to do", user_id)
        return docs

    if _enabled(families, "structured_intel"):
        docs.extend(await _ingest_structured_intel(watch))

    if not settings.ANAKIN_API_KEY:
        log.warning(
            "ANAKIN_API_KEY missing — skipping Anakin-backed ingest families"
        )
        return docs

    async with AnakinClient() as client:
        if _enabled(families, "high_value_urls"):
            urls = list((families.get("high_value_urls") or {}).get("urls") or [])
            docs.extend(await _ingest_url_scraper(client, urls))

        if _enabled(families, "agentic_search"):
            docs.extend(await _ingest_agentic(client, watch))

        wire_jobs = _collect_wire_jobs(families, watch)
        docs.extend(await _ingest_wire(client, wire_jobs))

    return docs


def _enabled(families: dict[str, Any], key: str) -> bool:
    fam = families.get(key) or {}
    return bool(fam.get("enabled", True))


# ---------- structured intel (OSV + NVD) ----------------------------------


async def _ingest_structured_intel(
    watch: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tasks: list[asyncio.Task[list[dict[str, Any]]]] = []

    async def _osv(item: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return await structured_intel.query_osv(
                item["name"], item.get("ecosystem", "software")
            )
        except Exception as err:
            log.warning("osv fail for %s: %s", item.get("name"), err)
            return []

    async def _nvd(item: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return await structured_intel.query_nvd(item["name"])
        except Exception as err:
            log.warning("nvd fail for %s: %s", item.get("name"), err)
            return []

    for item in watch:
        tasks.append(asyncio.create_task(_osv(item)))
        tasks.append(asyncio.create_task(_nvd(item)))

    docs: list[dict[str, Any]] = []
    for item, future in zip(_pair_items_to_tasks(watch), tasks):
        try:
            results = await future
        except Exception as err:
            log.warning("structured_intel task failed: %s", err)
            continue
        for entry in results:
            docs.append(_to_raw_doc(entry, family="structured_intel", item=item))

    return docs


def _pair_items_to_tasks(watch: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    """Yield each watch item twice (osv + nvd) — keeps zip alignment in
    :func:`_ingest_structured_intel` without a second pass."""

    for item in watch:
        yield item
        yield item


def _to_raw_doc(
    entry: dict[str, Any], *, family: str, item: dict[str, Any]
) -> dict[str, Any]:
    return {
        "url": entry.get("url", ""),
        "publisher": entry.get("publisher") or family,
        "title": entry.get("title") or "",
        "text": entry.get("text") or entry.get("title") or "",
        "family": family,
        "weight": _FAMILY_WEIGHTS.get(family, 30),
        "meta": {
            "raw": entry.get("raw"),
            "references": entry.get("references"),
        },
        "matched_dep_hint": _canonical(item),
    }


# ---------- URL scraper ---------------------------------------------------


async def _ingest_url_scraper(
    client: AnakinClient, urls: list[str]
) -> list[dict[str, Any]]:
    if not urls:
        return []

    settings = get_settings()
    batches = [urls[i : i + 10] for i in range(0, len(urls), 10)][
        : settings.MAX_URL_SCRAPER_BATCHES_PER_RUN
    ]
    docs: list[dict[str, Any]] = []
    for batch in batches:
        try:
            payload = await url_scraper.scrape_urls_batch(client, batch)
        except AnakinError as err:
            log.warning("url-scraper batch failed: %s", err)
            continue
        for result in payload.get("results") or []:
            if result.get("status") != "completed":
                continue
            text = (
                result.get("markdown")
                or result.get("cleanedHtml")
                or result.get("html")
                or ""
            )
            if not text:
                continue
            docs.append(
                {
                    "url": result.get("url", ""),
                    "publisher": _publisher_from_url(result.get("url", "")),
                    "title": result.get("url", ""),
                    "text": text,
                    "family": "url_scraper",
                    "weight": _FAMILY_WEIGHTS["url_scraper"],
                    "meta": {"index": result.get("index")},
                    "matched_dep_hint": "",
                }
            )
    return docs


def _publisher_from_url(url: str) -> str:
    if not url:
        return "url_scraper"
    if "://" not in url:
        return url
    host = url.split("://", 1)[1].split("/", 1)[0]
    return host or "url_scraper"


# ---------- agentic search -----------------------------------------------


async def _ingest_agentic(
    client: AnakinClient, watch: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not watch:
        return []
    # V1 only ever issues a single agentic prompt per run; the setting is a
    # kill-switch — bump to 0 to disable agentic search outright (e.g. when
    # demoing on a credit-tight account).
    if get_settings().MAX_AGENTIC_CALLS_PER_RUN < 1:
        return []
    names = ", ".join(item["name"] for item in watch[:25])
    prompt = (
        "List security incidents, breaches, CVEs, or vulnerabilities published "
        "in the last 48 hours that affect any of these dependencies: "
        f"{names}. For each finding return: title, affected dependency, severity hint, "
        "and a short summary citing source URLs."
    )
    try:
        payload = await agentic_search.research(client, prompt)
    except AnakinError as err:
        log.warning("agentic search failed: %s", err)
        return []

    if payload.get("status") != "completed":
        return []
    generated = payload.get("generatedJson") or {}
    summary = generated.get("summary") or ""
    structured = generated.get("structured_data") or {}
    if not summary and not structured:
        return []
    return [
        {
            "url": "https://anakin.io/agentic-search",
            "publisher": "Agentic Search",
            "title": f"Agentic research over {len(watch)} watchlist items",
            "text": summary
            + ("\n\n" + str(structured) if structured else ""),
            "family": "agentic",
            "weight": _FAMILY_WEIGHTS["agentic"],
            "meta": {"job_id": payload.get("id")},
            "matched_dep_hint": "",
        }
    ]


# ---------- wire (dynamic) ------------------------------------------------


def _collect_wire_jobs(
    families: dict[str, Any], watch: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """Build a flat ``[(slug, watch_item)]`` worklist capped by budget."""

    slugs: list[str] = []
    for fam_key in ("social_media", "news", "blogs", "high_value_urls", "package_registries"):
        fam = families.get(fam_key) or {}
        if not fam.get("enabled", True):
            continue
        slugs.extend(fam.get("wire_platform_slugs") or [])

    seen: set[str] = set()
    unique_slugs = [s for s in slugs if not (s in seen or seen.add(s))]

    cap = get_settings().MAX_WIRE_CALLS_PER_RUN
    jobs: list[tuple[str, dict[str, Any]]] = []
    for slug in unique_slugs:
        for item in watch:
            jobs.append((slug, item))
            if len(jobs) >= cap:
                return jobs
    return jobs


# Per-slug action search cache lives for the duration of one ingest_all() call.
_WireActionCache = dict[str, list[dict[str, Any]]]

# Tiered keyword sets for action picking. Search-style (real query input)
# beats security-leaning, which beats listy/feed-style as a last resort.
_TIER_SEARCH = re.compile(r"\bsearch\b|\bfind\b|\bquery\b|\blookup\b", re.IGNORECASE)
_TIER_SECURITY = re.compile(
    r"advis|securit|vuln|cve|exploit|breach|incident|issue|repo|pull request|pr\b",
    re.IGNORECASE,
)
_TIER_LISTY = re.compile(
    r"\blist\b|stor(?:y|ies)|articles?|news|discuss|posts?|feed|threads?|items?",
    re.IGNORECASE,
)
_ID_FIELD_NAMES = {
    "id",
    "item_id",
    "post_id",
    "comment_id",
    "username",
    "user",
    "user_id",
    "slug",
    "url",
    "uri",
    "thread_id",
}


async def _ingest_wire(
    client: AnakinClient, jobs: list[tuple[str, dict[str, Any]]]
) -> list[dict[str, Any]]:
    cache: _WireActionCache = {}
    docs: list[dict[str, Any]] = []

    for slug, item in jobs:
        actions = await _list_actions_cached(client, slug, cache)
        action = _choose_action(actions)
        if action is None:
            log.info("wire: no usable action for slug=%s", slug)
            continue
        params = _params_for_action(action, item["name"])
        try:
            job = await wire.run_action(
                client, action_id=action["action_id"], params=params
            )
        except AnakinError as err:
            log.warning(
                "wire run_action failed slug=%s action=%s: %s",
                slug,
                action.get("action_id"),
                err,
            )
            continue
        if job.get("status") != "completed":
            log.info(
                "wire job not completed slug=%s action=%s status=%s",
                slug,
                action.get("action_id"),
                job.get("status"),
            )
            continue
        text = _stringify_wire_data(job.get("data"))
        if not text.strip():
            continue
        docs.append(
            {
                "url": f"anakin://wire/{slug}/{action.get('action_id')}",
                "publisher": action.get("catalog_name") or slug,
                "title": f"{action.get('name', 'Wire action')} ({slug})",
                "text": text,
                "family": "wire",
                "weight": _FAMILY_WEIGHTS["wire"],
                "meta": {"slug": slug, "action_id": action.get("action_id")},
                "matched_dep_hint": _canonical(item),
            }
        )
    return docs


async def _list_actions_cached(
    client: AnakinClient, slug: str, cache: _WireActionCache
) -> list[dict[str, Any]]:
    """List actions for a slug via ``GET /v1/holocron/catalog/{slug}``.

    The catalog endpoint is the canonical action-discovery path per the
    Anakin docs and is more reliable than the search endpoint, which can
    500 for some slugs.
    """

    if slug in cache:
        return cache[slug]
    try:
        actions = await wire.list_actions(client, slug)
    except AnakinError as err:
        log.warning("wire list_actions failed slug=%s: %s", slug, err)
        actions = []
    cache[slug] = actions
    return actions


def _choose_action(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most likely 'search' action from a catalog's action list.

    PLATFORM_FLOW V1 picks "search/list/read" patterns per catalog. Each
    candidate is scored by keyword tier and by whether its required params
    are fillable from a watch item name. The action with the highest score
    wins; ties break on list order so behaviour is deterministic.
    """

    candidates = [a for a in actions if not a.get("auth_required")]
    if not candidates:
        return None

    best: tuple[int, int, dict[str, Any]] | None = None
    for idx, action in enumerate(candidates):
        score = _score_action(action)
        # Sort: higher score first, earlier index breaks ties.
        key = (-score, idx)
        if best is None or key < (-best[0], best[1]):
            best = (score, idx, action)
    return best[2] if best else None


def _score_action(action: dict[str, Any]) -> int:
    text = f"{action.get('name', '')} {action.get('description', '')}"
    score = 0
    if _TIER_SEARCH.search(text):
        score += 100
    if _TIER_SECURITY.search(text):
        score += 60
    if _TIER_LISTY.search(text):
        score += 30

    params = _normalize_params(action)
    has_query_field = False
    needs_specific_id = False
    for p in params:
        if not p.get("required"):
            continue
        n = (p.get("name") or "").lower()
        if n in _QUERY_FIELD_NAMES:
            has_query_field = True
        elif n in _ID_FIELD_NAMES:
            needs_specific_id = True

    if has_query_field:
        score += 50
    # An action that *needs* an ID/username we can't fabricate is mostly
    # useless for "scan for mentions of dep X" — only keep it as a last
    # resort.
    if needs_specific_id and not has_query_field:
        score -= 80
    return score


def _normalize_params(action: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the two ``params`` shapes Anakin returns into one list.

    - Live Wire catalogs return ``params`` as a list of descriptors:
      ``[{"name": "...", "type": "...", "required": true, ...}, ...]``
    - Some mocked / older payloads use a JSON Schema dict:
      ``{"type": "object", "properties": {...}, "required": [...]}``

    Both collapse to a uniform list of param dicts.
    """

    raw = action.get("params") or action.get("parameters") or []
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, dict)]
    if isinstance(raw, dict):
        out: list[dict[str, Any]] = []
        properties = raw.get("properties") or {}
        required = set(raw.get("required") or [])
        for name, prop in properties.items():
            entry = dict(prop) if isinstance(prop, dict) else {}
            entry["name"] = name
            entry["required"] = name in required
            out.append(entry)
        return out
    return []


_QUERY_FIELD_NAMES = {"query", "q", "keyword", "search", "search_term", "term"}
_LIMIT_FIELD_NAMES = {"limit", "count", "size", "per_page", "results_per_page"}
_OFFSET_FIELD_NAMES = {"offset", "page", "skip", "start"}
_DEFAULT_LIMIT = 10


def _params_for_action(action: dict[str, Any], value: str) -> dict[str, Any]:
    """Build a ``params`` dict for an Anakin Wire action.

    Per-action params vary widely — for example ``hn_stories`` takes
    ``type``/``limit``/``offset`` while ``hn_search`` takes a single
    required ``query``. Strategy:

    1. Required params get a sensible value: ``default`` if present, else
       enum first value, else watch name for query-style/string fields,
       else a typed zero/empty for non-string fields.
    2. Optional params are filled ONLY when there's a clear default we
       should send: explicit ``default``, recognised
       ``limit``/``offset`` numeric defaults, or query-style field names.

    We deliberately don't force the watch name into arbitrary unrequired
    string fields — e.g. ``hn_stories.type`` expects "top"/"new"/"best",
    not "lodash", and we'd rather call with ``{}`` and let the server
    default kick in than send a bad value.
    """

    params = _normalize_params(action)
    out: dict[str, Any] = {}

    for p in params:
        name = p.get("name")
        if not name or not p.get("required"):
            continue
        out[name] = _fill_param(p, value)

    for p in params:
        name = p.get("name")
        if not name or name in out:
            continue
        name_lc = name.lower()
        if "default" in p:
            out[name] = p["default"]
        elif name_lc in _LIMIT_FIELD_NAMES:
            out[name] = _DEFAULT_LIMIT
        elif name_lc in _OFFSET_FIELD_NAMES:
            out[name] = 0
        elif name_lc in _QUERY_FIELD_NAMES and p.get("type") == "string":
            out[name] = value

    return out


def _fill_param(p: dict[str, Any], value: str) -> Any:
    """Pick a value for one normalized param descriptor."""

    if "default" in p:
        return p["default"]
    enum = p.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    name_lc = (p.get("name") or "").lower()
    ptype = p.get("type")

    if name_lc in _QUERY_FIELD_NAMES:
        return value
    if name_lc in _LIMIT_FIELD_NAMES:
        return _DEFAULT_LIMIT
    if name_lc in _OFFSET_FIELD_NAMES:
        return 0

    if ptype == "string":
        return value
    if ptype == "integer":
        return 0
    if ptype == "number":
        return 0
    if ptype == "boolean":
        return False
    if ptype == "array":
        return []
    if ptype == "object":
        return {}
    return value


def _stringify_wire_data(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n\n".join(_stringify_wire_data(d) for d in data if d)
    if isinstance(data, dict):
        parts: list[str] = []
        for key in ("title", "name", "summary", "description", "text", "body", "content"):
            value = data.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
        if not parts:
            return str(data)[:4000]
        return "\n\n".join(parts)
    return str(data)
