"""Structured-intel sources that aren't behind Anakin: OSV + NVD.

These are plain JSON APIs; we use a short-lived ``httpx.AsyncClient`` per
call so the Anakin connection pool stays clean. Each function returns a list
of normalized advisory dicts the ingest layer can hand straight to the
normaliser.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import get_settings

log = logging.getLogger(__name__)


_OSV_URL = "https://api.osv.dev/v1/query"
_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

_OSV_ECOSYSTEMS = {
    "npm": "npm",
    "pypi": "PyPI",
    "go": "Go",
    "rubygems": "RubyGems",
    "maven": "Maven",
    "nuget": "NuGet",
    "cargo": "crates.io",
    "packagist": "Packagist",
    "composer": "Packagist",
}


def _make_client() -> httpx.AsyncClient:
    timeout = get_settings().HTTP_TIMEOUT_SECONDS
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "anakin-alerts/0.1"})


async def query_osv(name: str, ecosystem: str) -> list[dict[str, Any]]:
    """Query OSV for vulnerabilities affecting ``name`` in ``ecosystem``.

    Returns a list of (already-normalised) advisory dicts. Failures are
    logged and swallowed; a flaky third-party shouldn't sink a run.
    """

    ecosystem_label = _OSV_ECOSYSTEMS.get(ecosystem.lower())
    if not ecosystem_label:
        return []
    body = {"package": {"name": name, "ecosystem": ecosystem_label}}
    try:
        async with _make_client() as http:
            response = await http.post(_OSV_URL, json=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as err:
        log.warning("osv query failed for %s:%s — %s", ecosystem, name, err)
        return []

    items: list[dict[str, Any]] = []
    for vuln in payload.get("vulns", []) or []:
        identifier = vuln.get("id", "")
        url = (
            f"https://osv.dev/vulnerability/{identifier}"
            if identifier
            else "https://osv.dev/"
        )
        items.append(
            {
                "url": url,
                "publisher": "OSV",
                "title": vuln.get("summary") or identifier or "OSV advisory",
                "text": vuln.get("details") or vuln.get("summary") or "",
                "severity_hints": [s.get("score") for s in vuln.get("severity", []) if s.get("score")],
                "references": [r.get("url") for r in vuln.get("references", []) if r.get("url")],
                "affected_name": name,
                "affected_ecosystem": ecosystem,
                "raw": vuln,
            }
        )
    return items


async def query_nvd(name: str) -> list[dict[str, Any]]:
    """Query NVD for CVEs mentioning ``name``."""

    params = {"keywordSearch": name, "resultsPerPage": 10}
    try:
        async with _make_client() as http:
            response = await http.get(_NVD_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as err:
        log.warning("nvd query failed for %s — %s", name, err)
        return []

    items: list[dict[str, Any]] = []
    for entry in payload.get("vulnerabilities", []) or []:
        cve = entry.get("cve") or {}
        cve_id = cve.get("id", "")
        descriptions = cve.get("descriptions") or []
        text = ""
        for d in descriptions:
            if d.get("lang") == "en":
                text = d.get("value", "")
                break
        url = (
            f"https://nvd.nist.gov/vuln/detail/{cve_id}"
            if cve_id
            else "https://nvd.nist.gov/"
        )
        items.append(
            {
                "url": url,
                "publisher": "NVD",
                "title": cve_id or "NVD advisory",
                "text": text,
                "affected_name": name,
                "raw": cve,
            }
        )
    return items
