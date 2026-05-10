"""APScheduler bridge.

Boots a single :class:`BackgroundScheduler` inside the FastAPI lifespan
and re-runs :func:`enqueue_hourly_runs` every ``RUN_INTERVAL_MINUTES``.
Because Celery is eager, the task body executes inline on the scheduler's
thread — no broker, no worker process needed.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings
from . import celery_app  # noqa: F401  (ensures tasks are registered)
from .tasks import enqueue_hourly_runs

log = logging.getLogger(__name__)

_HOURLY_JOB_ID = "enqueue_hourly_runs"


def _trigger_hourly_runs() -> None:
    try:
        enqueue_hourly_runs.delay()
    except Exception as err:
        log.exception("hourly fan-out failed: %s", err)


def start_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _trigger_hourly_runs,
        trigger=IntervalTrigger(minutes=settings.RUN_INTERVAL_MINUTES),
        id=_HOURLY_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler


def shutdown_scheduler(scheduler: BackgroundScheduler) -> None:
    try:
        scheduler.shutdown(wait=False)
    except Exception as err:
        log.warning("scheduler shutdown error: %s", err)
