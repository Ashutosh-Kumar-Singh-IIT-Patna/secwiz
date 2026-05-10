"""FastAPI factory.

Boots:

* :class:`JsonStore` singleton bound to ``settings.DATA_FILE``.
* The eager Celery app (so worker code paths import cleanly).
* APScheduler ``BackgroundScheduler`` running ``enqueue_hourly_runs`` every
  ``RUN_INTERVAL_MINUTES``. Because Celery is in EAGER mode, that task
  executes inline on the scheduler's thread.
* Routers under ``/v1``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, onboard, runs, wire_catalog
from .config import configure_logging, get_settings
from .queue.scheduler import shutdown_scheduler, start_scheduler
from .store.json_store import get_store

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()
    store = get_store(settings.data_file_path)
    log.info("store ready at %s", store.path)

    scheduler = start_scheduler()
    log.info(
        "scheduler started; hourly runs every %s minutes",
        settings.RUN_INTERVAL_MINUTES,
    )

    try:
        yield
    finally:
        shutdown_scheduler(scheduler)
        log.info("scheduler stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Security Alerts Copilot",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(onboard.router)
    app.include_router(wire_catalog.router)
    app.include_router(runs.router)
    return app


app = create_app()
