"""Celery tasks.

The hourly tick fans out to :func:`run_for_user` per user. ``run_for_user``
is the single source of truth for what "one run" means — both the
APScheduler hourly trigger and the demo ``POST /v1/runs/trigger`` endpoint
go through it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .celery_app import celery_app

from ..services.pipeline import alert as alert_module
from ..services.pipeline.cluster import cluster_into_events
from ..services.pipeline.ingest import ingest_all
from ..services.pipeline.judge import judge_events
from ..services.pipeline.match import match_to_watchlist
from ..services.pipeline.normalize import normalize_docs
from ..services.pipeline.score import score_events, should_alert
from ..store.ids import new_id
from ..store.json_store import get_store

log = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="run_for_user",
)
def run_for_user(self, user_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return _run_for_user_sync(user_id)


@celery_app.task(name="enqueue_hourly_runs")
def enqueue_hourly_runs() -> dict[str, int]:
    store = get_store()
    users = store.users.all()
    count = 0
    for user in users:
        run_for_user.delay(user["id"])
        count += 1
    log.info("enqueue_hourly_runs fanned out to %d user(s)", count)
    return {"users": count}


def _run_for_user_sync(user_id: str) -> dict[str, Any]:
    store = get_store()
    user = store.users.get(user_id)
    if not user:
        log.warning("run_for_user: unknown user_id=%s", user_id)
        return {"error": "unknown user", "user_id": user_id}

    run_id = new_id("run")
    started = datetime.now(tz=timezone.utc).isoformat()
    error_msg: str | None = None
    stats: dict[str, Any] = {
        "docs": 0,
        "candidates": 0,
        "events": 0,
        "alerts_sent": 0,
    }

    try:
        watch = store.watch_items.by_user(user_id)
        cfg_record = store.source_configs.by_user(user_id)
        cfg = (cfg_record or {}).get("config") or {}

        raw_docs = asyncio.run(ingest_all(user_id, watch, cfg))
        normalized = normalize_docs(store, raw_docs)
        candidates = match_to_watchlist(normalized, watch)
        clusters = cluster_into_events(candidates)
        scored = score_events(clusters)
        judged = asyncio.run(judge_events(scored))
        sent = alert_module.dispatch_alerts(
            store, user, judged, should_alert=should_alert
        )

        suppressed_by_llm = sum(1 for ev in judged if ev.get("suppressed"))
        stats.update(
            {
                "docs": len(normalized),
                "candidates": len(candidates),
                "events": len(judged),
                "alerts_sent": sent,
                "llm_suppressed": suppressed_by_llm,
            }
        )
    except Exception as err:
        log.exception("run_for_user failed for %s: %s", user_id, err)
        error_msg = repr(err)

    finished = datetime.now(tz=timezone.utc).isoformat()
    record = store.runs.append(
        {
            "id": run_id,
            "user_id": user_id,
            "started_at": started,
            "finished_at": finished,
            "stats": stats,
            "error": error_msg,
        }
    )
    log.info(
        "run_for_user done user=%s stats=%s error=%s", user_id, stats, error_msg
    )
    return record
