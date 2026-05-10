"""Shared pytest fixtures.

The store + settings live in module-level singletons (process-wide), so
between tests we reset them and point ``DATA_FILE`` at a fresh tmp path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

# Add backend/ to sys.path so `from app...` works regardless of how pytest
# is invoked.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _isolate_settings_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    data_file = tmp_path / "store.json"
    monkeypatch.setenv("DATA_FILE", str(data_file))
    monkeypatch.setenv("DEMO_TRIGGER_TOKEN", "test-token")
    monkeypatch.setenv("EMAIL_DRY_RUN", "true")
    monkeypatch.setenv("RUN_INTERVAL_MINUTES", "60")
    # ANAKIN_API_KEY is preserved if the user set it (live tests need it).

    # Clear caches so settings + store re-pick up the env.
    from app.config import get_settings
    from app.store import json_store

    get_settings.cache_clear()
    json_store.reset_store_for_tests()

    yield data_file

    get_settings.cache_clear()
    json_store.reset_store_for_tests()


@pytest.fixture
def store(_isolate_settings_and_store: Path):
    """A fresh :class:`JsonStore` bound to ``tmp_path/store.json``."""

    from app.store.json_store import get_store

    return get_store(_isolate_settings_and_store)


@pytest.fixture
def make_user(store):
    def _make(email: str = "test@example.com") -> dict:
        return store.users.upsert_by_email(email)

    return _make


@pytest.fixture
def make_watch_items(store, make_user):
    def _make(items=None, email: str = "test@example.com") -> tuple[dict, list[dict]]:
        user = make_user(email)
        items = items or [
            {"ecosystem": "npm", "name": "lodash", "raw_input": "lodash"},
            {"ecosystem": "pypi", "name": "requests", "raw_input": "requests"},
        ]
        written = store.watch_items.replace_for_user(user["id"], items)
        return user, written

    return _make


@pytest.fixture
def fastapi_client(_isolate_settings_and_store):
    """A FastAPI ``TestClient`` whose lifespan binds the store to tmp_path."""

    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def has_anakin_key() -> bool:
    return bool(os.environ.get("ANAKIN_API_KEY"))


def pytest_collection_modifyitems(config, items):
    """Skip live tests when their respective API keys aren't set.

    We read keys from :class:`Settings` (which loads ``.env``) and also
    promote them into ``os.environ`` so live tests that pass the key
    directly (``os.environ["ANAKIN_API_KEY"]``) keep working too.
    """

    from app.config import get_settings

    settings = get_settings()
    if settings.ANAKIN_API_KEY:
        os.environ.setdefault("ANAKIN_API_KEY", settings.ANAKIN_API_KEY)
    if settings.GEMINI_API_KEY:
        os.environ.setdefault("GEMINI_API_KEY", settings.GEMINI_API_KEY)

    skip_anakin = pytest.mark.skip(
        reason="ANAKIN_API_KEY not set; skipping live test"
    )
    skip_gemini = pytest.mark.skip(
        reason="GEMINI_API_KEY not set; skipping live test"
    )
    has_anakin = bool(settings.ANAKIN_API_KEY)
    has_gemini = bool(settings.GEMINI_API_KEY)
    for item in items:
        if "live_anakin" in item.keywords and not has_anakin:
            item.add_marker(skip_anakin)
        if "live_gemini" in item.keywords and not has_gemini:
            item.add_marker(skip_gemini)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live_anakin: hits the real Anakin API; needs ANAKIN_API_KEY"
    )
    config.addinivalue_line(
        "markers", "live_gemini: hits the real Gemini API; needs GEMINI_API_KEY"
    )
