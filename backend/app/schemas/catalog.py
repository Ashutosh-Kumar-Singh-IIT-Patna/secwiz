"""Wire catalog response shape."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WireCatalogItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    name: str
    domain: str | None = None
    category: str | None = None
    auth_required: bool = False


class WireCatalogResponse(BaseModel):
    items: list[WireCatalogItemOut]
    fetched_at: datetime
    cached: bool
