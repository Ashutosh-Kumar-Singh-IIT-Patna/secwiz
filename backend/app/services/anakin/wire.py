"""Wire (Holocron) helpers.

Wraps the five Wire HTTP endpoints documented at
``/docs/api-reference/holocron``:

* :func:`list_catalogs`   — ``GET  /v1/holocron/catalog``         (used by ``GET /v1/wire-catalog``)
* :func:`get_catalog`     — ``GET  /v1/holocron/catalog/{slug}``  (canonical action discovery)
* :func:`list_actions`    — convenience wrapper around ``get_catalog``
* :func:`search_actions`  — ``GET  /v1/holocron/search``          (cross-catalog action search)
* :func:`submit_task`     — ``POST /v1/holocron/task``            (kick off a job)
* :func:`get_job`         — ``GET  /v1/holocron/jobs/{id}``       (poll a job)
* :func:`run_action`      — :func:`submit_task` + :func:`get_job` poll loop

V1 ingest skips actions with ``auth_required: true`` so we never need a
``credential_id`` (multi-auth identities are not yet wired in). Both
``mode: "async"`` and ``mode: "sync"`` actions work transparently —
sync ones either return ``{status: "completed", data: ...}`` from the
POST itself (no ``job_id``) or complete on the very first GET.

Rate limits per the docs (per user): ``POST /holocron/task`` is 20/min,
``GET /holocron/jobs/{id}`` is 60/min. The ingest loop submits and polls
sequentially, so at our worst (4 jobs/run, ~3s poll) we stay well under
both caps.
"""

from __future__ import annotations

import logging
from typing import Any

from .client import AnakinClient, poll_until_done

log = logging.getLogger(__name__)


async def list_catalogs(client: AnakinClient) -> list[dict[str, Any]]:
    """``GET /v1/holocron/catalog`` — every visible catalog as ``CatalogEntry``.

    Returns the unwrapped ``catalog`` array. Empty list on a non-dict
    response (e.g. unexpected upstream payload).
    """

    payload = await client.get("/holocron/catalog")
    return payload.get("catalog", []) if isinstance(payload, dict) else []


async def get_catalog(client: AnakinClient, slug: str) -> dict[str, Any]:
    """``GET /v1/holocron/catalog/{slug}`` — one catalog + all its actions.

    Per the docs this is "the canonical way to discover an action's
    ``action_id``, parameter schema, mode (``async`` / ``sync``), and
    credit cost". Empirically more reliable than
    ``/v1/holocron/search?catalog=<slug>``, which has been observed to 500
    for some slugs. Returns the raw ``{catalog, actions}`` dict.
    """

    payload = await client.get(f"/holocron/catalog/{slug}")
    if not isinstance(payload, dict):
        return {"catalog": None, "actions": []}
    return payload


async def list_actions(client: AnakinClient, slug: str) -> list[dict[str, Any]]:
    """Convenience: fetch a catalog and return its ``actions`` list."""

    payload = await get_catalog(client, slug)
    return payload.get("actions", []) or []


async def search_actions(
    client: AnakinClient,
    *,
    query: str | None = None,
    catalog: str | None = None,
    category: str | None = None,
    auth: bool | None = None,
) -> list[dict[str, Any]]:
    """``GET /v1/holocron/search`` — cross-catalog action search.

    All four query params are optional and combine with AND semantics per
    the docs. ``auth=False`` excludes auth-required actions. We send each
    only when explicitly set so the request is the minimal documented form.
    """

    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if catalog:
        params["catalog"] = catalog
    if category:
        params["category"] = category
    if auth is not None:
        params["auth"] = "true" if auth else "false"
    payload = await client.get("/holocron/search", params=params)
    return payload.get("results", []) if isinstance(payload, dict) else []


async def submit_task(
    client: AnakinClient,
    *,
    action_id: str,
    params: dict[str, Any] | None = None,
    credential_id: str | None = None,
) -> dict[str, Any]:
    """``POST /v1/holocron/task`` — body is ``{action_id, credential_id?, params?}``.

    Optional fields are only included when set so we never send empty
    ``params: {}`` or ``credential_id: null`` (the docs treat both as
    "field omitted").
    """

    body: dict[str, Any] = {"action_id": action_id}
    if params:
        body["params"] = params
    if credential_id:
        body["credential_id"] = credential_id
    return await client.post("/holocron/task", json=body)


async def get_job(client: AnakinClient, job_id: str) -> dict[str, Any]:
    """``GET /v1/holocron/jobs/{id}`` — terminal status is ``completed`` or ``failed``."""

    return await client.get(f"/holocron/jobs/{job_id}")


async def run_action(
    client: AnakinClient,
    *,
    action_id: str,
    params: dict[str, Any] | None = None,
    credential_id: str | None = None,
) -> dict[str, Any]:
    """Submit a Wire task, poll until done, return the full job payload.

    For ``mode: "sync"`` actions the POST may return the completed result
    inline (no ``job_id``). In that case we skip polling and hand the
    submission response back as the job payload — the shape is identical:
    ``{status: "completed", data: {...}}``.
    """

    submitted = await submit_task(
        client, action_id=action_id, params=params, credential_id=credential_id
    )
    job_id = submitted.get("job_id") or submitted.get("id")
    if not job_id:
        # Sync action, or a malformed response we can't poll. Either way,
        # propagate the original payload so the caller can inspect status.
        log.info("wire submit returned no job_id (sync mode?): %s", submitted)
        return submitted
    return await poll_until_done(lambda: get_job(client, job_id))
