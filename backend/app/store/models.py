"""Pydantic record models persisted in ``store.json``.

The shapes here track the JSON-as-DB schema in IMPLEMENTATION_PLAN.md §3.
Keep them flat and forgiving: ``extra = "allow"`` so older JSON snapshots
written by an earlier version of the app still load.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class UserRecord(_Record):
    id: str
    email: EmailStr
    created_at: datetime = Field(default_factory=utcnow)


class WatchItemRecord(_Record):
    id: str
    user_id: str
    ecosystem: str
    name: str
    raw_input: str
    aliases: list[str] = Field(default_factory=list)
    version_spec: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SourceConfigRecord(_Record):
    user_id: str
    config: dict[str, Any]
    updated_at: datetime = Field(default_factory=utcnow)


class SourceDocumentRecord(_Record):
    id: str
    url: str
    publisher: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
    content_hash: str
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SecurityEventRecord(_Record):
    id: str
    title: str
    summary: str = ""
    status: Literal["rumor", "confirmed", "patch_released"] = "rumor"
    severity: int = 0
    confidence: int = 0
    canonical_dep: str | None = None
    first_seen: datetime = Field(default_factory=utcnow)
    last_updated: datetime = Field(default_factory=utcnow)


class EventSignalRecord(_Record):
    event_id: str
    source_document_id: str
    family: str
    weight: int


class RelevanceMatchRecord(_Record):
    event_id: str
    watch_item_id: str
    score: int
    reason: str = ""


class AlertRecord(_Record):
    id: str
    user_id: str
    event_id: str
    severity: int
    confidence: int
    channel: Literal["email"] = "email"
    state: Literal["queued", "sent", "failed", "dry_run"] = "queued"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class RunRecord(_Record):
    id: str
    user_id: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class WireCatalogItem(_Record):
    slug: str
    name: str
    domain: str | None = None
    category: str | None = None
    auth_required: bool = False


class WireCatalogCache(_Record):
    fetched_at: datetime
    items: list[WireCatalogItem]
