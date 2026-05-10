"""Crawl wrapper (multi-page scraping under a starting URL)."""

from __future__ import annotations

from typing import Any

from .client import AnakinClient, poll_until_done


async def submit(
    client: AnakinClient,
    *,
    url: str,
    max_pages: int = 10,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    use_browser: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": url,
        "maxPages": max_pages,
        "useBrowser": use_browser,
    }
    if include_patterns:
        body["includePatterns"] = include_patterns
    if exclude_patterns:
        body["excludePatterns"] = exclude_patterns
    return await client.post("/crawl", json=body)


async def get(client: AnakinClient, job_id: str) -> dict[str, Any]:
    return await client.get(f"/crawl/{job_id}")


async def crawl(
    client: AnakinClient,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    submitted = await submit(client, url=url, **kwargs)
    job_id = submitted.get("jobId") or submitted.get("id")
    if not job_id:
        return submitted
    return await poll_until_done(lambda: get(client, job_id))
