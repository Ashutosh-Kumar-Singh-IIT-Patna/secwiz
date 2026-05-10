"""Celery app, run in EAGER mode for V1.

We keep the Celery interface so the V2 migration to a real Redis broker is
purely a config-flip — nothing in :mod:`app.queue.tasks` or any caller
needs to change.

In eager mode, ``task.delay(...)`` and ``task.apply_async(...)`` execute
synchronously on the calling thread. APScheduler triggers
:func:`enqueue_hourly_runs` from a background thread; ``run_for_user`` then
runs inline there.
"""

from __future__ import annotations

from celery import Celery

celery_app = Celery("security_alerts_copilot")
celery_app.conf.update(
    broker_url="memory://",
    result_backend="cache+memory://",
    task_always_eager=True,
    task_eager_propagates=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Importing tasks at module load registers them on `celery_app`.
from . import tasks  # noqa: E402,F401  (side-effect import)
