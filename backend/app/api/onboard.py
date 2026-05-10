"""Onboarding endpoint.

V1 strategy: replace watch items + source_config for the user on every
submit. Idempotent on email — second call with the same email re-uses the
existing user record but overwrites the watchlist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..schemas.onboard import (
    OnboardRequest,
    OnboardResponse,
    source_config_to_dict,
)
from ..store.json_store import get_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["onboard"])


@router.post("/onboard", response_model=OnboardResponse)
async def onboard(payload: OnboardRequest) -> OnboardResponse:
    store = get_store()
    user = store.users.upsert_by_email(payload.email)

    raw_items = [dep.model_dump() for dep in payload.dependencies]
    written = store.watch_items.replace_for_user(user["id"], raw_items)
    store.source_configs.replace_for_user(
        user["id"], source_config_to_dict(payload.source_config)
    )

    log.info(
        "onboard ok user_id=%s deps=%d email=%s",
        user["id"],
        len(written),
        payload.email,
    )
    return OnboardResponse(user_id=user["id"], watch_item_count=len(written))
