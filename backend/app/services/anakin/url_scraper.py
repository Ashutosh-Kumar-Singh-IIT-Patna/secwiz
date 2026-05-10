"""URL Scraper wrapper (single + batch + poll)."""

from __future__ import annotations

import logging
from typing import Any

from .client import AnakinClient, poll_until_done

log = logging.getLogger(__name__)


async def submit_single(
    client: AnakinClient,
    *,
    url: str,
    use_browser: bool = False,
    country: str = "us",
    generate_json: bool = False,
) -> dict[str, Any]:
    return await client.post(
        "/url-scraper",
        json={
            "url": url,
            "country": country,
            "useBrowser": use_browser,
            "generateJson": generate_json,
        },
    )


async def submit_batch(
    client: AnakinClient,
    *,
    urls: list[str],
    use_browser: bool = False,
    country: str = "us",
    generate_json: bool = False,
) -> dict[str, Any]:
    if not urls:
        raise ValueError("urls must not be empty")
    if len(urls) > 10:
        raise ValueError("batch supports at most 10 urls")
    return await client.post(
        "/url-scraper/batch",
        json={
            "urls": urls,
            "country": country,
            "useBrowser": use_browser,
            "generateJson": generate_json,
        },
    )


async def get_job(client: AnakinClient, job_id: str) -> dict[str, Any]:
    return await client.get(f"/url-scraper/{job_id}")


async def scrape_url(
    client: AnakinClient,
    url: str,
    *,
    use_browser: bool = False,
    country: str = "us",
) -> dict[str, Any]:
    submitted = await submit_single(
        client, url=url, use_browser=use_browser, country=country
    )
    job_id = submitted.get("jobId") or submitted.get("id")
    if not job_id:
        return submitted
    return await poll_until_done(lambda: get_job(client, job_id))


async def scrape_urls_batch(
    client: AnakinClient,
    urls: list[str],
    *,
    use_browser: bool = False,
    country: str = "us",
) -> dict[str, Any]:
    submitted = await submit_batch(
        client, urls=urls, use_browser=use_browser, country=country
    )
    job_id = submitted.get("jobId") or submitted.get("id")
    if not job_id:
        return submitted
    return await poll_until_done(lambda: get_job(client, job_id))
