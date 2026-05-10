"""Demo trigger endpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..queue.tasks import run_for_user
from ..store.json_store import get_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["runs"])


class TriggerRequest(BaseModel):
    user_id: str


class TriggerResponse(BaseModel):
    ok: bool = True
    run: dict[str, Any]


def _run_in_worker_thread(user_id: str) -> dict[str, Any]:
    """Eager Celery executes ``.delay`` inline; we need a real thread so
    the inner ``asyncio.run`` in ``run_for_user`` doesn't collide with
    FastAPI's running loop."""

    result = run_for_user.delay(user_id)
    return result.get(disable_sync_subtasks=False)


@router.post("/runs/trigger", response_model=TriggerResponse)
async def trigger(
    payload: TriggerRequest,
    x_demo_token: str | None = Header(default=None, alias="X-Demo-Token"),
) -> TriggerResponse:
    settings = get_settings()
    if not x_demo_token or x_demo_token != settings.DEMO_TRIGGER_TOKEN:
        raise HTTPException(status_code=401, detail="bad X-Demo-Token")

    store = get_store()
    if not store.users.get(payload.user_id):
        raise HTTPException(status_code=404, detail="unknown user_id")

    log.info("demo trigger user=%s", payload.user_id)
    record = await asyncio.to_thread(_run_in_worker_thread, payload.user_id)
    return TriggerResponse(run=record)
