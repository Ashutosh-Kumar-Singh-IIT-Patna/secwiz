"""Wire catalog endpoint (proxy + 24 h cache)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from ..config import get_settings
from ..schemas.catalog import WireCatalogItemOut, WireCatalogResponse
from ..services.anakin import wire as wire_service
from ..services.anakin.client import AnakinClient, AnakinError
from ..store.json_store import get_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["catalog"])


def _normalise(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for entry in items:
        slug = entry.get("slug")
        if not slug:
            continue
        out.append(
            {
                "slug": slug,
                "name": entry.get("name") or slug,
                "domain": entry.get("domain"),
                "category": entry.get("category"),
                "auth_required": bool(entry.get("auth_required", False)),
            }
        )
    return out


@router.get("/wire-catalog", response_model=WireCatalogResponse)
async def get_wire_catalog(
    refresh: bool = Query(default=False, description="Bypass cache."),
) -> WireCatalogResponse:
    settings = get_settings()
    store = get_store()
    cached = store.wire_catalog_cache.get()

    if cached and not refresh:
        try:
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            fetched_at = None
        ttl = timedelta(seconds=settings.WIRE_CATALOG_TTL_SECONDS)
        if fetched_at and datetime.now(tz=timezone.utc) - fetched_at < ttl:
            return WireCatalogResponse(
                items=[WireCatalogItemOut(**i) for i in cached["items"]],
                fetched_at=fetched_at,
                cached=True,
            )

    if not settings.ANAKIN_API_KEY:
        if cached:
            log.warning(
                "ANAKIN_API_KEY missing; serving stale wire catalog cache"
            )
            try:
                fetched_at = datetime.fromisoformat(cached["fetched_at"])
            except (KeyError, ValueError):
                fetched_at = datetime.now(tz=timezone.utc)
            return WireCatalogResponse(
                items=[WireCatalogItemOut(**i) for i in cached["items"]],
                fetched_at=fetched_at,
                cached=True,
            )
        raise HTTPException(
            status_code=503,
            detail="ANAKIN_API_KEY not configured and no cached catalog",
        )

    async with AnakinClient() as client:
        try:
            raw = await wire_service.list_catalogs(client)
        except AnakinError as err:
            raise HTTPException(
                status_code=502,
                detail=f"anakin upstream error {err.status}",
            ) from err

    items = _normalise(raw)
    fresh = store.wire_catalog_cache.set(items)
    fetched_at = datetime.fromisoformat(fresh["fetched_at"])
    return WireCatalogResponse(
        items=[WireCatalogItemOut(**i) for i in items],
        fetched_at=fetched_at,
        cached=False,
    )
