"""Single source of truth for runtime config.

Loaded from environment + a ``.env`` file (in ``backend/`` or the project
root). Validation happens once at import time so misconfiguration is loud and
early.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _candidate_env_files() -> tuple[Path, ...]:
    """Look for `.env` in backend/ first, then project root."""
    here = Path(__file__).resolve()
    backend_dir = here.parent.parent
    candidates = [backend_dir / ".env", backend_dir.parent / ".env"]
    return tuple(p for p in candidates if p.exists()) or (backend_dir / ".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_candidate_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ANAKIN_API_KEY: str = ""
    ANAKIN_BASE_URL: str = "https://api.anakin.io/v1"

    # Gemini judge — used as a second-opinion gate over the deterministic
    # severity/confidence scoring. Empty key = judge disabled, runs fall
    # back to deterministic-only scoring.
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    # ``gemini-flash-latest`` is a rolling alias that always points at the
    # current generation flash model with free-tier quota — pinning to a
    # specific version like ``gemini-2.0-flash`` will burn out as Google
    # rotates free-tier eligibility. Override per env if you need a fixed
    # version for reproducibility.
    GEMINI_MODEL: str = "gemini-flash-latest"
    MAX_GEMINI_CALLS_PER_RUN: int = 8
    GEMINI_PREFILTER_MIN_SEVERITY: int = 35

    # Email transport — SendGrid Web API (HTTPS:443).
    # ``EMAIL_FROM`` must match a verified Single Sender / domain identity
    # in your SendGrid account. Leave EMAIL_DRY_RUN=true to log alerts
    # instead of actually sending — useful for local demos.
    SENDGRID_API_KEY: str = ""
    SENDGRID_API_BASE: str = "https://api.sendgrid.com/v3"
    EMAIL_FROM: str = ""
    EMAIL_DRY_RUN: bool = True

    DEMO_TRIGGER_TOKEN: str = "changeme"

    DATA_FILE: str = "backend/data/store.json"

    HTTP_TIMEOUT_SECONDS: float = 30.0
    ANAKIN_POLL_INTERVAL_SECONDS: float = 3.0
    ANAKIN_POLL_MAX_SECONDS: float = 180.0

    RUN_INTERVAL_MINUTES: int = 60
    INGEST_CONCURRENCY: int = 5

    LOG_LEVEL: str = "INFO"

    WIRE_CATALOG_TTL_SECONDS: int = 60 * 60 * 24

    # Per-run cost caps. Keep these low for hackathon demos so a single
    # ingest_all() never burns more than a handful of Anakin credits.
    MAX_WIRE_CALLS_PER_RUN: int = 4
    MAX_AGENTIC_CALLS_PER_RUN: int = 1
    MAX_URL_SCRAPER_BATCHES_PER_RUN: int = 2

    # Content-hash dedup window for normalize_docs(). Drop to 0 to disable
    # dedup entirely (useful for demos where you want every run to re-emit).
    DEDUP_WINDOW_HOURS: int = 24

    @property
    def data_file_path(self) -> Path:
        path = Path(self.DATA_FILE)
        if not path.is_absolute():
            here = Path(__file__).resolve()
            path = (here.parent.parent.parent / path).resolve()
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("kombu").setLevel(logging.ERROR)
    logging.getLogger("celery").setLevel(logging.WARNING)
