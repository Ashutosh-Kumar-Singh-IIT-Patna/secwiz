"""Agentic Search wrapper.

Anakin's 4-stage research pipeline. Submit a prompt, receive a ``job_id``,
poll until ``completed``. The completed payload exposes
``generatedJson.summary`` plus ``generatedJson.structured_data`` — we hand
the full payload back to the ingest layer and let it normalise.
"""

from __future__ import annotations

from typing import Any

from .client import AnakinClient, poll_until_done


async def submit(client: AnakinClient, *, prompt: str) -> dict[str, Any]:
    return await client.post("/agentic-search", json={"prompt": prompt})


async def get(client: AnakinClient, job_id: str) -> dict[str, Any]:
    return await client.get(f"/agentic-search/{job_id}")


async def research(client: AnakinClient, prompt: str) -> dict[str, Any]:
    submitted = await submit(client, prompt=prompt)
    job_id = submitted.get("job_id") or submitted.get("id")
    if not job_id:
        return submitted
    return await poll_until_done(
        lambda: get(client, job_id),
        interval_s=10.0,
    )
