"""Synchronous AI-powered web search (``POST /v1/search``)."""

from __future__ import annotations

from typing import Any

from .client import AnakinClient


async def search(
    client: AnakinClient, prompt: str, limit: int = 5
) -> list[dict[str, Any]]:
    payload = await client.post(
        "/search", json={"prompt": prompt, "limit": limit}
    )
    return payload.get("results", []) if isinstance(payload, dict) else []
